#!/usr/bin/env python

# @author: Bo Xin
# @      Large Synoptic Survey Telescope

# main function

import os
import argparse
# import numpy as np

from aosWFS import aosWFS
from aosEstimator import aosEstimator
from aosController import aosController
from aosMetric import aosMetric
from aosM1M3 import aosM1M3
from aosM2 import aosM2
from aosTeleState import aosTeleState


def main():
    parser = argparse.ArgumentParser(
        description='-----LSST Integrated Model------')

    parser.add_argument('iSim', type=int, help='sim#')
    parser.add_argument('-icomp', type=int,
                        help='override icomp in the estimator parameter file, \
                        default=no override')
    parser.add_argument('-izn3', type=int,
                        help='override izn3 in the estimator parameter file, \
                        default=no override')
    parser.add_argument('-start', dest='startiter', type=int, default=0,
                        help='iteration No. to start with, default=0')
    parser.add_argument('-end', dest='enditer', type=int, default=5,
                        help='iteration No. to end with, default=5')
    parser.add_argument('-sensor', dest='sensor', choices = ('ideal','covM','phosim','cwfs','load'),
                        help='ideal: use true wavefront in estimator;\
                        covM: use covarance matrix to estimate wavefront;\
                        phosim: run Phosim to create WFS images;\
                        cwfs: start by running cwfs on existing images;\
                        load: load wavefront from txt files')
    parser.add_argument('-ctrloff', help='w/o applying ctrl rules or regenrating pert files',
                        action='store_true')
    parser.add_argument('-opdoff', help='w/o regenerating OPD maps',
                        action='store_true')
    parser.add_argument('-psfoff', help='w/o regenerating psf images',
                        action='store_true')
    parser.add_argument('-pssnoff', help='w/o calculating PSSN',
                        action='store_true')
    parser.add_argument('-ellioff', help='w/o calculating ellipticity',
                        action='store_true')
    parser.add_argument('-makesum', help='make summary plot, assuming all data available',
                        action='store_true')
    parser.add_argument('-p', dest='numproc', default=1, type=int,
                        help='Number of Processors Phosim uses')
    parser.add_argument('-g', dest='gain', default=0.7, type=float,
                        help='override gain in the controller parameter file, \
                        default=no override')
    parser.add_argument('-i', dest='instruParam',
                        default='single_dof',
                        help='instrument parameter file in data/, \
                        default=single_dof')
    parser.add_argument('-e', dest='estimatorParam',
                        default='pinv',
                        help='estimator parameter file in data/, default=pinv')
    parser.add_argument('-c', dest='controllerParam',
                        default='optiPSSN', choices=('optiPSSN', 'null'),
                        help='controller parameter file in data/, \
                        default=optiPSSN')
    parser.add_argument('-w', dest='wavelength', type=float,
                        default=0.5, help='wavelength in micron, default=0.5')
    parser.add_argument('-d', dest='debugLevel', type=int,
                        default=0, choices=(-1, 0, 1, 2, 3),
                        help='debug level, -1=quiet, 0=Zernikes, \
                        1=operator, 2=expert, 3=everything, default=0')
    parser.add_argument('-baserun', dest='baserun', default=-1, type=int,
                        help='iter0 is same as this run, so skip iter0')
    args = parser.parse_args()
    if args.makesum:
        args.sensor = 'ideal'
        args.ctrloff = True
        args.opdoff = True
        args.psfoff = True
        args.pssnoff = True
        args.ellioff = True
        
    if args.debugLevel >= 1:
        print(args)

    # *****************************************
    # simulate the perturbations
    # *****************************************
    M1M3 = aosM1M3(args.debugLevel)
    M2 = aosM2(args.debugLevel)
    phosimDir = '../phosimSE/'
    #znPert = 28  # znmax used in pert file to define surfaces

    # *****************************************
    # run wavefront sensing algorithm
    # *****************************************
    cwfsDir = '../../wavefront/cwfs/'
    instruFile = 'lsst'
    algoFile = 'exp'
    wfs = aosWFS(cwfsDir, instruFile, algoFile,
                 128, args.wavelength, args.debugLevel)

    #cwfsInstru = 'lsst'
    #cwfsAlgo = 'exp'
    cwfsModel = 'offAxis'

    # *****************************************
    # state estimator
    # *****************************************
    esti = aosEstimator(args.estimatorParam, wfs, args.icomp, args.izn3,
                        args.debugLevel)
    # state is defined after esti, b/c, for example, ndof we use in state
    # depends on the estimator.
    pertDir = 'pert/sim%d' % args.iSim
    if not os.path.isdir(pertDir):
        os.makedirs(pertDir)
    imageDir = 'image/sim%d' % args.iSim
    if not os.path.isdir(imageDir):
        os.makedirs(imageDir)
    state = aosTeleState(esti, args.instruParam, args.iSim, phosimDir,
                         pertDir, imageDir, args.debugLevel)
    # *****************************************
    # control algorithm
    # *****************************************
    metr = aosMetric(state, wfs, args.debugLevel)
    ctrl = aosController(args.controllerParam, esti, metr, wfs, M1M3, M2,
                         args.wavelength, args.gain, args.debugLevel)

    # *****************************************
    # start the Loop
    # *****************************************
    for iIter in range(args.startiter, args.enditer + 1):
        if args.debugLevel >= 3:
            print('iteration No. %d' % iIter)

        state.setIterNo(wfs, metr, iIter)

        if not args.ctrloff:
            if iIter > 0: #args.startiter:
                esti.estimate(state, wfs, ctrl, args.sensor)
                ctrl.getMotions(esti, metr, args.wavelength)
                ctrl.drawControlPanel(esti, state)

                # need to remake the pert file here.
                # It will be inserted into OPD.inst, PSF.inst later
                state.update(ctrl)

            state.writePertFile(esti)

        if args.baserun>0 and iIter == 0:
            state.getOPD35fromBase(args.baserun, metr)
            state.getPSF31fromBase(args.baserun, metr)
            metr.getPSSNandMorefromBase(args.baserun, state)
            metr.getEllipticityfromBase(args.baserun, state)
            
        else:
            state.getOPD35(args.opdoff, wfs, metr, args.numproc, args.wavelength,
                           args.debugLevel)

            state.getPSF31(args.psfoff, metr, args.numproc, args.debugLevel)
    
            metr.getPSSNandMore(args.pssnoff, state, wfs, args.wavelength, args.numproc, args.debugLevel)
    
            metr.getEllipticity(args.ellioff, state, wfs, args.wavelength, args.numproc, args.debugLevel)
    
            if not (args.sensor == 'ideal' or args.sensor == 'covM'):
                if args.sensor == 'phosim' and not iIter == args.enditer:
                    #state.getWFS4(wfs, metr, args.numproc, args.debugLevel)
                    #wfs.preprocess(state, metr, args.debugLevel)
                    wfs.parallelCwfs(cwfsModel, args.numproc, args.debugLevel)
                    wfs.checkZ4C(state, metr, args.debugLevel)

    ctrl.drawSummaryPlots(state, metr, esti, M1M3, M2,
                          args.startiter, args.enditer, args.debugLevel)

if __name__ == "__main__":
    main()
