#!/usr/bin/env python
##
# @authors: Bo Xin
# @       Large Synoptic Survey Telescope

import os
import glob
import multiprocessing
import copy

import numpy as np
from astropy.io import fits
from scipy import ndimage
import matplotlib.pyplot as plt

from lsst.cwfs.algorithm import Algorithm
from lsst.cwfs.instrument import Instrument
from lsst.cwfs.image import Image, readFile


class aosWFS(object):

    def __init__(self, cwfsDir, instruFile, algoFile,
                 imgSizeinPix, band, wavelength, debugLevel):
        self.nWFS = 4
        self.nRun = 1
        self.nExp = 2
        if instruFile[:6] == 'comcam':
            self.nWFS = 9
            self.nRun = 2
            self.nExp = 1 #only 1 set of intra and 1 set of extra for each iter
        self.wfsName = ['intra', 'extra']
        self.offset = [-1.5, 1.5]  # default offset
        if (instruFile[:6] == 'comcam' and len(instruFile) == 8) or \
                (instruFile[:4] == 'lsst' and len(instruFile) == 6):
            aa = float(instruFile[-2:]) / 10
            self.offset = [-aa, aa]

        self.halfChip = ['C0', 'C1']  # C0 is always intra, C1 is extra

        aosDir = os.getcwd()
        self.cwfsDir = cwfsDir
        os.chdir(cwfsDir)
        self.inst = Instrument(instruFile, imgSizeinPix)
        self.algo = Algorithm(algoFile, self.inst, debugLevel)
        os.chdir(aosDir)
        self.znwcs = self.algo.numTerms
        self.znwcs3 = self.znwcs - 3
        self.myZn = np.zeros((self.znwcs3 * self.nWFS, 2))
        self.trueZn = np.zeros((self.znwcs3 * self.nWFS, 2))
        aa = instruFile
        if aa[-2:].isdigit():
            aa = aa[:-2]
        aosSrcDir = os.path.split(os.path.abspath(__file__))[0]
        intrinsicFile = '%s/../data/%s/intrinsic_zn.txt' % (aosSrcDir, aa)
        if np.abs(wavelength - 0.5)>1e-3:
            intrinsicFile = intrinsicFile.replace(
                'zn.txt', 'zn_%s.txt' % band.upper())
        intrinsicAll = np.loadtxt(intrinsicFile)
        intrinsicAll = intrinsicAll * wavelength
        self.intrinsicWFS = intrinsicAll[
            -self.nWFS:, 3:self.algo.numTerms].reshape((-1, 1))
        self.covM = np.loadtxt('%s/../data/covM86.txt'% aosSrcDir)  # in unit of nm^2
        if self.nWFS > 4:
            nrepeat = int(np.ceil(self.nWFS / 4))
            self.covM = np.tile(self.covM, (nrepeat, nrepeat))
            self.covM = self.covM[
                :(self.znwcs3 * self.nWFS), :(self.znwcs3 * self.nWFS)]
        self.covM = self.covM * 1e-6  # in unit of um^2

        if debugLevel >= 3:
            print('znwcs3=%d' % self.znwcs3)
            print(self.intrinsicWFS.shape)
            print(self.intrinsicWFS[:5])

    def preprocess(self, state, metr, debugLevel):
        for iexp in range(0, self.nExp):
            for iField in range(metr.nFieldp4 - self.nWFS, metr.nFieldp4):
                chipStr, px0, py0 = state.fieldXY2Chip(
                    metr.fieldXp[iField], metr.fieldYp[iField], debugLevel)
                for ioffset in [0, 1]:
                    if self.nRun == 1:
                        src = glob.glob('%s/iter%d/*%d*%s*%s*E00%d.fits' %
                                        (state.imageDir, state.iIter,
                                            state.obsID,
                                        chipStr, self.halfChip[ioffset], iexp))
                    else:
                        src = glob.glob('%s/iter%d/*%d*%s*%s*E00%d.fits' %
                                        (state.imageDir, state.iIter,
                                            state.obsID + ioffset,
                                        chipStr, self.halfChip[ioffset], iexp))                
                    chipFile = src[0]
                    chipImage, header = fits.getdata(chipFile,header=True)
                        
                    if state.inst[:4] == 'lsst':
                        if ioffset == 0:
                            # intra image, C0, pulled 0.02 deg from right edge
                            # degree to micron then to pixel
                            px = int(px0 - 0.020 * 180000 / 10)
                        elif ioffset == 1:
                            # extra image, C1, pulled 0.02 deg away from left edge
                            px = int(px0 + 0.020 * 180000 / 10 - chipImage.shape[1])
                    elif state.inst[:6] == 'comcam':
                        px = px0
                    py = copy.copy(py0)
    
                    # psf here is 4 x the size of cwfsStampSize, to get centroid
                    psf = chipImage[np.max((0, py - 2 * state.cwfsStampSize)):
                                    py + 2 * state.cwfsStampSize,
                                    np.max((0, px - 2 * state.cwfsStampSize)):
                                    px + 2 * state.cwfsStampSize]
                    centroid = ndimage.measurements.center_of_mass(psf)
                    offsety = centroid[0] - 2 * state.cwfsStampSize + 1
                    offsetx = centroid[1] - 2 * state.cwfsStampSize + 1
                    # if the psf above has been cut on px=0 or py=0 side
                    if py - 2 * state.cwfsStampSize < 0:
                        offsety -= py - 2 * state.cwfsStampSize
                    if px - 2 * state.cwfsStampSize < 0:
                        offsetx -= px - 2 * state.cwfsStampSize
    
                    psf = chipImage[
                        int(py - state.cwfsStampSize / 2 + offsety):
                        int(py + state.cwfsStampSize / 2 + offsety),
                        int(px - state.cwfsStampSize / 2 + offsetx):
                        int(px + state.cwfsStampSize / 2 + offsetx)]
    
                    if state.inst[:4] == 'lsst':
                        # readout of corner raft are identical,
                        # cwfs knows how to handle rotated images
                        # note: rot90 rotates the array,
                        # not the image (as you see in ds9, or Matlab with
                        #                  "axis xy")
                        # that is why we need to flipud and then flip back
                        if iField == metr.nField:
                            psf = np.flipud(np.rot90(np.flipud(psf), 2))
                        elif iField == metr.nField + 1:
                            psf = np.flipud(np.rot90(np.flipud(psf), 3))
                        elif iField == metr.nField + 3:
                            psf = np.flipud(np.rot90(np.flipud(psf), 1))
    
                    # below, we have 0 b/c we may have many
                    stampFile = '%s/iter%d/sim%d_iter%d_wfs%d_%s_0_E00%d.fits' % (
                        state.imageDir, state.iIter, state.iSim, state.iIter,
                        iField, self.wfsName[ioffset], iexp)
                    if os.path.isfile(stampFile):
                        os.remove(stampFile)
                    hdu = fits.PrimaryHDU(psf)
                    hdu.writeto(stampFile)

                    if ((iField == metr.nFieldp4 - self.nWFS) and (ioffset == 0)):
                        fid = open(state.atmFile[iexp], 'w')
                        fid.write('Layer# \t seeing \t L0 \t\t wind_v \t wind_dir\n')
                        for ilayer in range(7):
                            fid.write('%d \t %.6f \t %.5f \t %.6f \t %.6f\n'%(
                                ilayer,header['SEE%d'%ilayer],
                                header['OSCL%d'%ilayer],
                                header['WIND%d'%ilayer],
                                header['WDIR%d'%ilayer]))
                        fid.close()
                    
                    if debugLevel >= 3:
                        print('px = %d, py = %d' % (px, py))
                        print('offsetx = %d, offsety = %d' % (offsetx, offsety))
                        print('passed %d, %s' % (iField, self.wfsName[ioffset]))
    
            # make an image of the 8 donuts
            for iField in range(metr.nFieldp4 - self.nWFS, metr.nFieldp4):
                chipStr, px, py = state.fieldXY2Chip(
                    metr.fieldXp[iField], metr.fieldYp[iField], debugLevel)
                for ioffset in [0, 1]:
                    src = glob.glob('%s/iter%d/sim%d_iter%d_wfs%d_%s_*E00%d.fits' % (
                        state.imageDir, state.iIter, state.iSim, state.iIter,
                        iField, self.wfsName[ioffset], iexp))
                    IHDU = fits.open(src[0])
                    psf = IHDU[0].data
                    IHDU.close()
                    if state.inst[:4] == 'lsst':
                        nRow = 2
                        nCol = 4
                        if iField == metr.nField:
                            pIdx = 3 + ioffset  # 3 and 4
                        elif iField == metr.nField + 1:
                            pIdx = 1 + ioffset  # 1 and 2
                        elif iField == metr.nField + 2:
                            pIdx = 5 + ioffset  # 5 and 6
                        elif iField == metr.nField + 3:
                            pIdx = 7 + ioffset  # 7 and 8
                    elif state.inst[:6] == 'comcam':
                        nRow = 3
                        nCol = 6
                        ic = np.floor(iField / nRow)
                        ir = iField % nRow
                        # does iField=0 give 13 and 14?
                        pIdx = int((nRow - ir - 1) * nCol + ic * 2 + 1 + ioffset)
                        # print('pIdx = %d, chipStr= %s'%(pIdx, chipStr))
                    plt.subplot(nRow, nCol, pIdx)
                    plt.imshow(psf, origin='lower', interpolation='none')
                    plt.title('%s_%s' %
                              (chipStr, self.wfsName[ioffset]), fontsize=10)
                    plt.axis('off')
    
            # plt.show()
            pngFile = '%s/iter%d/sim%d_iter%d_wfs_E00%d.png' % (
                state.imageDir, state.iIter, state.iSim, state.iIter, iexp)
            plt.savefig(pngFile, bbox_inches='tight')
    
            # write out catalog for good wfs stars
            fid = open(self.catFile[iexp], 'w')
            for i in range(metr.nFieldp4 - self.nWFS, metr.nFieldp4):
                intraFile = glob.glob('%s/iter%d/sim%d_iter%d_wfs%d_%s_*E00%d.fits' % (
                    state.imageDir, state.iIter, state.iSim, state.iIter, i, 
                    self.wfsName[0], iexp))[0]
                extraFile = glob.glob('%s/iter%d/sim%d_iter%d_wfs%d_%s_*E00%d.fits' % (
                    state.imageDir, state.iIter, state.iSim, state.iIter, i,
                    self.wfsName[1], iexp))[0]
                if state.inst[:4] == 'lsst':
                    if i == 31:
                        fid.write('%9.6f %9.6f %9.6f %9.6f %s %s\n' % (
                            metr.fieldXp[i] - 0.020, metr.fieldYp[i],
                            metr.fieldXp[i] + 0.020, metr.fieldYp[i],
                            intraFile, extraFile))
                    elif i == 32:
                        fid.write('%9.6f %9.6f %9.6f %9.6f %s %s\n' % (
                            metr.fieldXp[i], metr.fieldYp[i] - 0.020,
                            metr.fieldXp[i], metr.fieldYp[i] + 0.020,
                            intraFile, extraFile))
                    elif i == 33:
                        fid.write('%9.6f %9.6f %9.6f %9.6f %s %s\n' % (
                            metr.fieldXp[i] + 0.020, metr.fieldYp[i],
                            metr.fieldXp[i] - 0.020, metr.fieldYp[i],
                            intraFile, extraFile))
                    elif i == 34:
                        fid.write('%9.6f %9.6f %9.6f %9.6f %s %s\n' % (
                            metr.fieldXp[i], metr.fieldYp[i] + 0.020,
                            metr.fieldXp[i], metr.fieldYp[i] - 0.020,
                            intraFile, extraFile))
                elif state.inst[:6] == 'comcam':
                    fid.write('%9.6f %9.6f %9.6f %9.6f %s %s\n' % (
                        metr.fieldXp[i], metr.fieldYp[i],
                        metr.fieldXp[i], metr.fieldYp[i],
                        intraFile, extraFile))
            fid.close()

    def parallelCwfs(self, cwfsModel, numproc, debugLevel):
        for iexp in range(0, self.nExp):
            argList = []
            fid = open(self.catFile[iexp])
            for line in fid:
                data = line.split()
                I1Field = [float(data[0]), float(data[1])]
                I2Field = [float(data[2]), float(data[3])]
                I1File = data[4]
                I2File = data[5]
                argList.append((I1File, I1Field, I2File, I2Field,
                                self.inst, self.algo, cwfsModel))
            fid.close()
            # test, pdb cannot go into the subprocess
            # aa = runcwfs(argList[0])
            # aa = runcwfs(argList[4])

            pool = multiprocessing.Pool(numproc)
            zcarray = pool.map(runcwfs, argList)
            pool.close()
            pool.join()
            zcarray = np.array(zcarray)

            np.savetxt(self.zFile[iexp], zcarray)

    def checkZ4C(self, state, metr, debugLevel):
        z4c = np.loadtxt(self.zFile[0])  # in micron
        z4cE001 = np.loadtxt(self.zFile[1])
        z4cTrue = np.zeros((metr.nFieldp4, self.znwcs, state.nOPDw))
        aa = np.loadtxt(state.zTrueFile)
        for i in range(state.nOPDw):
            z4cTrue[:, :, i] = aa[i*metr.nFieldp4:(i+1)*metr.nFieldp4, :]

        x = range(4, self.znwcs + 1)
        plt.figure(figsize=(10, 8))
        if state.inst[:4] == 'lsst':
            # subplots go like this
            #  2 1
            #  3 4
            pIdx = [2, 1, 3, 4]
            nRow = 2
            nCol = 2
        elif state.inst[:6] == 'comcam':
            pIdx = [7, 4, 1, 8, 5, 2, 9, 6, 3]
            nRow = 3
            nCol = 3

        for i in range(self.nWFS):
            chipStr, px, py = state.fieldXY2Chip(
                metr.fieldXp[i + metr.nFieldp4 - self.nWFS],
                metr.fieldYp[i + metr.nFieldp4 - self.nWFS], debugLevel)
            plt.subplot(nRow, nCol, pIdx[i])
            plt.plot(x, z4c[i, :self.znwcs3], label='CWFS_E000',
                     marker='*', color='r', markersize=6)
            plt.plot(x, z4cE001[i, :self.znwcs3], label='CWFS_E001',
                     marker='v', color='g', markersize=6)
            for irun in range(state.nOPDw):
                if irun==0:
                    mylabel = 'Truth'
                else:
                    mylabel = ''
                plt.plot(x, z4cTrue[i + metr.nFieldp4 - self.nWFS, 3:self.znwcs,
                                        irun],
                             label=mylabel,
                        marker='.', color='b', markersize=10)
            if ((state.inst[:4] == 'lsst' and (i == 1 or i == 2)) or
                    (state.inst[:6] == 'comcam' and (i <= 2))):
                plt.ylabel('$\mu$m')
            if ((state.inst[:4] == 'lsst' and (i == 2 or i == 3)) or
                    (state.inst[:6] == 'comcam' and (i % nRow == 0))):
                plt.xlabel('Zernike Index')
            leg = plt.legend(loc="best")
            leg.get_frame().set_alpha(0.5)
            plt.grid()
            plt.title('Zernikes %s' % chipStr, fontsize=10)

        plt.savefig(self.zCompFile, bbox_inches='tight')

    def getZ4CfromBase(self, baserun, state):
        for iexp in range(self.nExp):
            if not os.path.isfile(self.zFile[iexp]):
                baseFile = self.zFile[iexp].replace(
                    'sim%d' % state.iSim, 'sim%d' % baserun)
                os.link(baseFile, self.zFile[iexp])
        if not os.path.isfile(self.zCompFile):
            baseFile = self.zCompFile.replace(
                'sim%d' % state.iSim, 'sim%d' % baserun)
            os.link(baseFile, self.zCompFile)


def runcwfs(argList):
    I1File = argList[0]
    I1Field = argList[1]
    I2File = argList[2]
    I2Field = argList[3]
    inst = argList[4]
    algo = argList[5]
    model = argList[6]

    I1 = Image(readFile(I1File), I1Field, 'intra')
    I2 = Image(readFile(I2File), I2Field, 'extra')
    algo.reset(I1, I2)
    algo.runIt(inst, I1, I2, model)

    return np.append(algo.zer4UpNm * 1e-3, algo.caustic)
