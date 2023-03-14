#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
MICA pipe Quality Check script:

Generates a pdf file for QC of the processing

    Parameters
    ----------

    sub      : str, subject identification

    out       : Output directory for the processed files <derivatives>

    bids      : Path to BIDS Directory

    ses       : OPTIONAL flag that indicates the session name (if omitted will manage ase SINGLE session)

    tracts    : OPTIONAL number of streamlines, where 'M' stands for millions (default=40M)

    tmpDir    : OPTIONAL specifcation of temporary directory location <path> (Default is /tmp)

    quiet     : OPTIONAL do not print comments

    nocleanup : OPTIONAL do not delete temporary directory at script completion

    version   : OPTIONAL print software version


    USAGE
    --------
    >>> QC.py -sub <subject_id> -out <outputDirectory> -bids <BIDS-directory>

  McGill University, MNI, MICA-lab, Created 13 September 2022
  https://github.com/MICA-MNI/micapipe
  http://mica-mni.github.io/

  author: alexander-ngo
"""

from xhtml2pdf import pisa
import sys
import pandas as pd
import os
import argparse
import json
import glob
import nibabel as nb
from nibabel.freesurfer.mghformat import load
import numpy as np
import matplotlib as plt
import matplotlib.pyplot as pltpy
from brainspace.plotting import plot_hemispheres
from brainspace.mesh.mesh_io import read_surface
from brainspace.mesh.mesh_operations import combine_surfaces
from brainspace.utils.parcellation import map_to_labels
from brainspace.vtk_interface import wrap_vtk, serial_connect
from brainspace.datasets import load_conte69
from vtk import vtkPolyDataNormals

# Arguments
parser = argparse.ArgumentParser()

# Required
parser.add_argument('-sub',
                    dest='sub',
                    type=str,
                    help='Subject identification',
                    required=True
                    )

parser.add_argument('-out',
                    dest='out',
                    type=str,
                    help='Output directory for the processed files <derivatives>',
                    required=True
                    )

parser.add_argument('-bids',
                    dest='bids',
                    type=str,
                    help='Path to BIDS Directory',
                    required=True
                    )

parser.add_argument('-ses',
                    dest='ses',
                    type=str,
                    default='',
                    help='Flag that indicates the session name'
                    )

parser.add_argument('-tracts',
                    dest='tracts',
                    type=str,
                    default='40M',
                    help='Number of streamlines'
                    )

parser.add_argument('-tmpDir',
                    dest='tmpDir',
                    type=str,
                    default='/tmp',
                    help='Path to temporary directory location'
                    )

parser.add_argument('-quiet',
                    action='store_false',
                    help='Print comments? {True, False}'
                    )

parser.add_argument('-nocleanup',
                    action='store_false',
                    help='Delete temporary directory at script completion? {True, False}'
                    )


parser.add_argument('-version',
                    action='store_false',
                    help='Print software version? {True, False}'
                    )

args = parser.parse_args()

# Arguments
sub = args.sub
out = os.path.realpath(args.out)
bids = os.path.realpath(args.bids)
ses = args.ses
tracts = args.tracts
tmpDir = args.tmpDir
quiet = args.nocleanup
version = args.version

# Optional inputs:
# Session
if ses == "":
    ses_number = "Not defined"
    sbids = sub
else:
    ses_number = ses
    ses = "ses-" + ses_number
    sbids = sub + "_" + ses

derivatives = out.split('/micapipe_v0.2.0')[0]

# Path to MICAPIPE
MICAPIPE=os.popen("echo $MICAPIPE").read()[:-1]


## ------------------------------------------------------------------------- ##
##                                                                           ##
##                      Helper functions to generate PDF                     ##
##                                                                           ##
## ------------------------------------------------------------------------- ##
def check_json_exist_complete(jsonPath=''):
    # Check if json file exists:
    json_exist = os.path.isfile(jsonPath)

    # Check if module is complete
    module_description = os.path.realpath(jsonPath)
    with open( module_description ) as f:
        module_description = json.load(f)
    json_complete = module_description["Status"] == "COMPLETED"

    return json_exist and json_complete


def report_header_template(sub='', ses_number='', dataset_name='', MICAPIPE=''):
    # Header
    report_header = (
        # Micapipe banner
        '<img id=\"top\" src=\"{MICAPIPE}/docs/figures/micapipe_long.png\" alt=\"micapipe\">'

        # Dataset name
        '<h1 style="color:#343434;font-family:Helvetica, sans-serif !important;text-align:center;margn-bottom:0">'
        '{dataset_name} <h1>'

        # Subject's ID | Session
        '<h3 style="color:#343434;font-family:Helvetica, sans-serif;text-align:center;margin-bottom:25px">'
        '<b>Subject</b>: {sub} &nbsp | &nbsp <b>Session</b>: {ses_number} </h3>'
    )
    return report_header.format(sub=sub, ses_number=ses_number, dataset_name=dataset_name, MICAPIPE=MICAPIPE)

# Header template
def report_module_header_template(module=''):
    # Module header:
    report_module_header = (
        '<p style="border:2px solid #666;padding-top:10px;padding-left:5px;background-color:#eee;font-family:Helvetica, '
        'sans-serif;font-size:14px">'
        '<b>Module: {module}</b> <p>'
    )
    return report_module_header.format(module=module)

# QC Summary
def report_qc_summary_template(jsonPath=''):
    module_description = os.path.realpath(jsonPath)
    with open( module_description ) as f:
        module_description = json.load(f)
    module = module_description["Module"]
    status = module_description["Status"]
    progress = module_description["Progress"]
    time = module_description["Processing.time"]
    threads = module_description["Threads"]
    micapipe_version = module_description["micapipeVersion"]
    date = module_description["Date"]

    # QC summary table
    report_qc_summary = (
        '<p style="font-family:Helvetica, sans-serif;font-size:12px;text-align:Left;margin-bottom:0px">'
        '<b>QC summary</b> </p>'

        '<table style="border:1px solid #666;width:100%">'
            # Status
            '<tr><td style=padding-top:4px;padding-left:3px;text-align:left>Status</td>'
            '<td style=padding-top:4px;padding-left:3px;text-align:left>{status}: {progress} steps completed</td></tr>'
            # Processing time
            '<tr><td style=padding-top:4px;padding-left:3px;text-align:left>Processing time</td>'
            '<td style=padding-top:4px;padding-left:3px;text-align:left>{time} minutes</td></tr>'
            # Thread
            '<tr><td style=padding-top:4px;padding-left:3px;text-align:left>Number of threads</td>'
            '<td style=padding-top:4px;padding-left:3px;text-align:left>{threads}</td></tr>'
            # Micapipe version
            '<tr><td style=padding-top:4px;padding-left:3px;text-align:left>Micapipe version</td>'
            '<td style=padding-top:4px;padding-left:3px;text-align:left>{micapipe_version}</td></tr>'
            # Date
            '<tr><td style=padding-top:4px;padding-left:3px;text-align:left>Date</td>'
            '<td style=padding-top:4px;padding-left:3px;text-align:left>{date}</td></tr>'
        '</table>'
    )
    return report_qc_summary.format(status=status, progress=progress, time=time, threads=threads, micapipe_version=micapipe_version, date=date)

# INPUT TEMPLATE
def report_module_input_template(inputs=[]):
    # Module inputs
    report_module_input = (
        # Module inputs:
        '<p style="font-family:Helvetica, sans-serif;font-size:12px;text-align:Left;margin-bottom:0">'
        '<b>Inputs</b> </p>'
    )

    _input = ''
    for i in inputs:
        _input_template = ('<ul><li>{i}</li></ul>')
        _input += _input_template.format(i=i)
    report_module_input += _input

    return report_module_input

# OUTPUT TEMPLATE
def report_module_output_template(outName='', outPath='', figPath=''):
    # Module Outputs
    report_module_output = (
        '<p style="font-family:Helvetica, sans-serif;font-size:10px;text-align:Left;margin-bottom:0px">'
        '<b> {outName} </b> </p>'

        '<p style="font-family:Helvetica, sans-serif;font-size:10px;text-align:Left;margin:0px">'
        'Filepath: <wbr>{outPath}</wbr> </p>'

        '<center> <img style="width:500px%;margin-top:0px" src="{figPath}"> </center>'
    )
    return report_module_output.format(outName=outName, outPath=outPath, figPath=figPath)


# NIFTI_CHECK (generate qc images from volumes)
def nifti_check(outName='', outPath='', refPath='', roi=False, figPath=''):

    if os.path.exists(outPath):
        if os.path.exists(refPath):
            ROI = '-roi' if roi else ''
            os.system("${MICAPIPE}/functions/nifti_capture.py -img %s %s %s -out %s"%(refPath, outPath, ROI, figPath))
        else:
            os.system("${MICAPIPE}/functions/nifti_capture.py -img %s -out %s"%(outPath, figPath))

        _static_block = report_module_output_template(outName=outName, outPath=outPath, figPath=figPath)
    else:
        _static_block = ('<p style="font-family:Helvetica, sans-serif;font-size:10px;text-align:Left;margin-bottom:0px">'
            '<b> {outName} </b> </p>'
            '<p style="font-family:Helvetica, sans-serif;font-size:10px;text-align:Left;margin:0px">'
            'Filepath: does not exist </p>').format(outName=outName)

    return _static_block

def load_surface(lh, rh, with_normals=True, join=False):
    """
    Loads surfaces.

    Parameters
    ----------
    with_normals : bool, optional
        Whether to compute surface normals. Default is True.
    join : bool, optional.
        If False, return one surface for left and right hemispheres. Otherwise,
        return a single surface as a combination of both left and right.
        surfaces. Default is False.

    Returns
    -------
    surf : tuple of BSPolyData or BSPolyData.
        Surfaces for left and right hemispheres. If ``join == True``, one
        surface with both hemispheres.
    """

    surfs = [None] * 2
    for i, side in enumerate([lh, rh]):
        surfs[i] = read_surface(side)
        if with_normals:
            nf = wrap_vtk(vtkPolyDataNormals, splitting=False,
                          featureAngle=0.1)
            surfs[i] = serial_connect(surfs[i], nf)

    if join:
        return combine_surfaces(*surfs)
    return surfs[0], surfs[1]

def cmap_gradient(N, base_cmaps=['inferno', 'Dark2', 'Set1', 'Set2']):
    """
    Creates a gradient color map of a defined lenght.

    Parameters
    ----------
    N     : int
         Number of colors to extract from each of the base_cmaps below.
    cmaps : list
        List of color map(s) to merge.

    Returns
    -------
    cmap : numpy ndarray
        Surfaces for left and right hemispheres. If ``join == True``, one
        surface with both hemispheres.
    """
    # number of colors
    N = 75

    # we go from 0.2 to 0.8 below to avoid having several whites and blacks in the resulting cmaps
    colors = np.concatenate([pltpy.get_cmap(name)(np.linspace(0,1,N)) for name in base_cmaps])
    cmap = plt.colors.ListedColormap(colors)
    return cmap

derivatives = out.split('/micapipe_v0.2.0')[0]

ColCurv= plt.colors.ListedColormap(['#A2CD5A', '#A0CA5B', '#9FC85C', '#9EC55D', '#9DC35E', '#9CC05F', '#9BBE61', '#9ABB62', '#99B963', '#98B664', '#96B465', '#95B166', '#94AF68', '#93AC69', '#92AA6A', '#91A76B', '#90A56C', '#8FA26D', '#8EA06F', '#8C9D70', '#8B9B71', '#8A9972', '#899673', '#889475', '#879176', '#868F77', '#858C78', '#848A79', '#82877A', '#81857C', '#80827D', '#7F807E', '#807D7D', '#827A7A', '#857777', '#877575', '#8A7272', '#8C6F6F', '#8F6C6C', '#916969', '#946666', '#966464', '#996161', '#9B5E5E', '#9D5B5B', '#A05858', '#A25656', '#A55353', '#A75050', '#AA4D4D', '#AC4A4A', '#AF4747', '#B14545', '#B44242', '#B63F3F', '#B93C3C', '#BB3939', '#BE3636', '#C03434', '#C33131', '#C52E2E', '#C82B2B', '#CA2828', '#CD2626'])


## ------------------------------------------------------------------------- ##
##                                                                           ##
##                              Build QC report                              ##
##                                                                           ##
## ------------------------------------------------------------------------- ##

## ---------------------------- MICAPIPE header ---------------------------- ##
def qc_header():
    dataset_description = os.path.realpath("%s/dataset_description.json"%(bids))
    with open( dataset_description ) as f:
        dataset_description = json.load(f)
    dataset_name = dataset_description["Name"]
    _static_block = report_header_template(sub=sub, ses_number=ses_number, dataset_name=dataset_name, MICAPIPE=MICAPIPE)

    return _static_block


## ------------------------ PROC-STRUCTURAL MODULE ------------------------- ##

def qc_proc_structural(proc_structural_json=''):

    if check_json_exist_complete(proc_structural_json):

        # QC header
        _static_block = qc_header()
        _static_block +=  report_module_header_template(module='proc_structural')

        # QC summary
        _static_block += report_qc_summary_template(proc_structural_json)

        # Inputs
        nativepro_json = os.path.realpath("%s/%s/%s/anat/%s_space-nativepro_T1w.json"%(out,sub,ses,sbids))
        with open( nativepro_json ) as f:
            nativepro_json = json.load(f)
        inputs = nativepro_json["inputsRawdata"].split(' ')
        _static_block += report_module_input_template(inputs=inputs)

        # Outputs
        _static_block += (
                '<p style="font-family:Helvetica, sans-serif;font-size:12px;text-align:Left;margin-bottom:0px">'
                '<b>Main outputs </b> </p>'
        )

        T1w_nativepro = "%s/%s/%s/anat/%s_space-nativepro_T1w.nii.gz"%(out,sub,ses,sbids)

        figPath = "%s/nativepro_T1w_screenshot.png"%(tmpDir)
        _static_block += nifti_check(outName="T1w nativepro", outPath=T1w_nativepro, figPath=figPath)

        outPath = "%s/%s/%s/anat/%s_space-nativepro_T1w_brain_mask.nii.gz"%(out,sub,ses,sbids)
        figPath = "%s/nativepro_T1w_brain_mask_screenshot.png"%(tmpDir)
        _static_block += nifti_check(outName="T1w nativepro brain mask", outPath=outPath, refPath=T1w_nativepro, figPath=figPath)

        outPath = "%s/nativepro_T1w_brain_5tt.nii.gz"%(tmpDir)
        figPath = "%s/nativepro_T1w_brain_5tt_screenshot.png"%(tmpDir)
        _static_block += nifti_check(outName="T1w nativepro 5 tissue segmentation (5TT)", outPath=outPath, refPath=T1w_nativepro, figPath=figPath)

        outPath = "%s/%s_space-MNI152_0.8_T1w_brain.nii.gz"%(tmpDir,sbids)
        MNI152_0_8mm = MICAPIPE + "/MNI152Volumes/MNI152_T1_0.8mm_brain_mask.nii.gz"
        figPath = "%s/nativepro_T1w_brain_mni152_08_screenshot.png"%(tmpDir)
        _static_block += nifti_check(outName="Registration: T1w nativepro in MNI152 0.8mm", outPath=MNI152_0_8mm, refPath=outPath, figPath=figPath)

        outPath = "%s/%s_space-MNI152_2_T1w_brain.nii.gz"%(tmpDir,sbids)
        MNI152_2mm = MICAPIPE + "/MNI152Volumes/MNI152_T1_2mm_brain_mask.nii.gz"
        figPath = "%s/nativepro_T1w_brain_mni152_2_screenshot.png"%(tmpDir)
        _static_block += nifti_check(outName="Registration: T1w nativepro in MNI152 2mm", outPath=MNI152_2mm, refPath=outPath, figPath=figPath)

        outPath =  "%s/%s/%s/anat/%s_space-nativepro_T1w_brain_pve_2.nii.gz"%(out,sub,ses,sbids)
        figPath = "%s/nativepro_T1w_brain_pve_2_screenshot.png"%(tmpDir)
        _static_block += nifti_check(outName="Partial volume: white matter", outPath=outPath, figPath=figPath)

        return _static_block

## --------------------------- PROC-SURF MODULE ---------------------------- ##
def qc_proc_surf(proc_surf_json=''):

    if check_json_exist_complete(proc_surf_json):

        # QC header
        _static_block = qc_header()

        surf_json = os.path.realpath("%s/%s/%s/surf/%s_proc_surf.json"%(out,sub,ses,sbids))
        with open( surf_json ) as f:
            surf_description = json.load(f)
        global recon
        recon = surf_description["SurfRecon"]
        global surfaceDir
        surfaceDir = surf_description["SurfaceDir"]
        _static_block +=  report_module_header_template(module="proc_surf (%s)"%(surf_description["SurfRecon"]))

        # QC summary
        _static_block += report_qc_summary_template(proc_surf_json)

        # Outputs
        _static_block += (
                '<p style="font-family:Helvetica, sans-serif;font-size:12px;text-align:Left;margin-bottom:0px">'
                '<b>Main outputs</b> </p>'
                '<p style="font-family:Helvetica, sans-serif;font-size:10px;text-align:Left;margin-bottom:0px">'
                '<b> Native surfaces </b> </p>'
        )

        # Load native surface
        global surf_lh, surf_rh, wm_lh, wm_rh, inf_lh, inf_rh
        surf_lh = read_surface(surfaceDir+'/'+sbids+'/surf/lh.pial', itype='fs')
        surf_rh = read_surface(surfaceDir+'/'+sbids+'/surf/rh.pial', itype='fs')
        wm_lh = read_surface(surfaceDir+'/'+sbids+'/surf/lh.white', itype='fs')
        wm_rh = read_surface(surfaceDir+'/'+sbids+'/surf/rh.white', itype='fs')
        inf_lh = read_surface(surfaceDir+'/'+sbids+'/surf/lh.inflated', itype='fs')
        inf_rh = read_surface(surfaceDir+'/'+sbids+'/surf/rh.inflated', itype='fs')

        # Native thickness
        th = np.concatenate((nb.freesurfer.read_morph_data(surfaceDir + '/' + sbids + '/surf/lh.thickness'), nb.freesurfer.read_morph_data(surfaceDir + '/' + sbids + '/surf/rh.thickness')), axis=0)
        plot_hemispheres(surf_lh, surf_rh, array_name=th, size=(900, 250), color_bar='bottom', zoom=1.25, embed_nb=True, interactive=False, share='both',
                         nan_color=(0, 0, 0, 1), color_range=(1.5, 4), cmap="inferno",transparent_bg=False,
                         screenshot = True, filename = tmpDir + '/' + sbids + '_space-fsnative_desc-surf_thickness.png')
        # Native curvature
        cv = np.concatenate((nb.freesurfer.read_morph_data(surfaceDir + '/' + sbids + '/surf/lh.curv'), nb.freesurfer.read_morph_data(surfaceDir + '/' + sbids + '/surf/rh.curv')), axis=0)
        plot_hemispheres(wm_lh, wm_rh, array_name=cv, size=(900, 250), color_bar='bottom', zoom=1.25, embed_nb=True, interactive=False, share='both',
                         nan_color=(0, 0, 0, 1), color_range=(-0.2, 0.2), cmap=ColCurv,transparent_bg=False,
                         screenshot = True, filename = tmpDir + '/' + sbids + '_space-fsnative_desc-surf_curv.png')
        # Native sulcal depth
        sd = np.concatenate((nb.freesurfer.read_morph_data(surfaceDir + '/' + sbids + '/surf/lh.sulc'), nb.freesurfer.read_morph_data(surfaceDir + '/' + sbids + '/surf/rh.sulc')), axis=0)
        plot_hemispheres(wm_lh, wm_rh, array_name=sd, size=(900, 250), color_bar='bottom', zoom=1.25, embed_nb=True, interactive=False, share='both',
                         nan_color=(0, 0, 0, 1), color_range=(-5, 5), cmap='cividis',transparent_bg=False,
                         screenshot = True, filename = tmpDir + '/' + sbids + '_space-fsnative_desc-surf_sulc.png')
        # Destrieux atlas (aparc.a2009s)
        parc = np.concatenate((nb.freesurfer.read_annot(surfaceDir + '/' + sbids + '/label/lh.aparc-a2009s_mics.annot')[0], nb.freesurfer.read_annot(surfaceDir + '/' + sbids + '/label/rh.aparc-a2009s_mics.annot')[0]), axis=0)
        plot_hemispheres(surf_lh, surf_rh, array_name=parc, size=(900, 250), zoom=1.25, embed_nb=True, interactive=False, share='both',
                         nan_color=(0, 0, 0, 1), cmap=cmap_gradient(len(np.unique(parc)), ['inferno', 'hsv', 'hsv', 'tab20b']),transparent_bg=False,
                         screenshot = True, filename = tmpDir + '/' + sbids + '_space-fsnative_desc-surf_a2009s.png')
        # Desikan-Killiany Atlas (aparc)
        parcDK = np.concatenate((nb.freesurfer.read_annot(surfaceDir + '/' + sbids + '/label/lh.aparc_mics.annot')[0], nb.freesurfer.read_annot(surfaceDir + '/' + sbids + '/label/rh.aparc_mics.annot')[0]), axis=0)
        plot_hemispheres(surf_lh, surf_rh, array_name=parcDK, size=(900, 250), zoom=1.25, embed_nb=True, interactive=False, share='both',
                         nan_color=(0, 0, 0, 1), cmap=cmap_gradient(len(np.unique(parcDK)), ['inferno', 'hsv', 'hsv', 'tab20b']), transparent_bg=False,
                         screenshot = True, filename = tmpDir + '/' + sbids + '_space-fsnative_desc-surf_aparc.png')

        native_surface_table = (
            '<table style="border:1px solid #666;width:100%">'
                # Thickness
                '<tr><td style=padding-top:4px;padding-bottom:4px;padding-left:3px;padding-right:3px;text-align:left>Thickness</td>'
                '<td style=padding-top:4px;padding-bottom:4px;padding-left:3px;padding-right:3px;text-align:center><img style="display:block;width:1500px%;margin-top:0px" src="{thPath}"></td></tr>'
                # Curvature
                '<tr><td style=padding-top:4px;padding-bottom:4px;padding-left:3px;padding-right:3px;text-align:left>Curvature</td>'
                '<td style=padding-top:4px;padding-bottom:4px;padding-left:3px;padding-right:3px;text-align:center><img style="display:block;width:1500px%;margin-top:0px" src="{cvPath}"></td></tr>'
                # Sulcal depth
                '<tr><td style=padding-top:4px;padding-bottom:4px;padding-left:3px;padding-right:3px;text-align:left>Sulcal depth</td>'
                '<td style=padding-top:4px;padding-bottom:4px;padding-left:3px;padding-right:3px;text-align:center><img style="display:block;width:1500px%;margin-top:0px" src="{sdPath}"></td></tr>'
                # Destrieux Atlas (aparc.a2009s)
                '<tr><td style=padding-top:4px;padding-bottom:4px;padding-left:3px;padding-right:3px;text-align:left>Destrieuz Atlas (aparc.a2009s)</td>'
                '<td style=padding-top:4px;padding-bottom:4px;padding-left:3px;padding-right:3px;text-align:center><img style="display:block;width:1500px%;margin-top:0px" src="{parcPath}"></td></tr>'
                # Desikan-Killiany Atlas (aparc)
                '<tr><td style=padding-top:4px;padding-bottom:4px;padding-left:3px;padding-right:3px;text-align:left>Desikan-Killiany Atlas (aparc)</td>'
                '<td style=padding-top:4px;padding-bottom:4px;padding-left:3px;padding-right:3px;text-align:center><img style="display:block;width:1500px%;margin-top:0px" src="{parcDKPath}"></td></tr>'
            '</table>'
        )

        _static_block += native_surface_table.format(thPath=tmpDir+'/'+sbids+'_space-fsnative_desc-surf_thickness.png',
            cvPath=tmpDir+'/'+sbids+'_space-fsnative_desc-surf_curv.png',
            sdPath=tmpDir+'/'+sbids+'_space-fsnative_desc-surf_sulc.png',
            parcPath=tmpDir+'/'+sbids+'_space-fsnative_desc-surf_a2009s.png',
            parcDKPath=tmpDir+'/'+sbids+'_space-fsnative_desc-surf_aparc.png'
        )

        return _static_block

## ------------------------- POST-STRUCTURAL MODULE ------------------------ ##
def qc_post_structural(post_structural_json=''):

    if check_json_exist_complete(post_structural_json):

        post_struct_json = os.path.realpath("%s/%s/%s/anat/%s_post_structural.json"%(out,sub,ses,sbids))
        with open( post_struct_json ) as f:
            post_struct_description = json.load(f)
        recon = post_struct_description["SurfaceProc"]

        # QC header
        _static_block = qc_header()
        _static_block +=  report_module_header_template(module='post_structural (%s)'%(recon))

        # QC summary
        _static_block += report_qc_summary_template(post_structural_json)

        # Main outputs
        _static_block += (
                '<p style="font-family:Helvetica, sans-serif;font-size:12px;text-align:Left;margin-bottom:0px">'
                '<b>Main outputs </b> </p>'
        )

        # Regitration/atlases
        outPath = post_struct_description["NativeSurfSpace"]["fileName"]
        refPath = "%s/%s/%s/anat/%s_space-fsnative_T1w.nii.gz"%(out,sub,ses,sbids)
        figPath = "%s/nativepro_T1w_fsnative_screenshot.png"%(tmpDir)
        _static_block += nifti_check(outName="Registration: T1w nativepro in %s native space"%(recon), outPath=outPath, refPath=refPath, figPath=figPath)

        outPath = "%s/%s/%s/parc/%s_space-nativepro_T1w_atlas-cerebellum.nii.gz"%(out,sub,ses,sbids)
        refPath = "%s/%s/%s/anat/%s_space-nativepro_T1w.nii.gz"%(out,sub,ses,sbids)
        figPath = "%s/nativepro_T1w_cerebellum_screenshot.png"%(tmpDir)
        _static_block += nifti_check(outName="T1w nativepro cerebellum atlas", outPath=outPath, refPath=refPath, figPath=figPath, roi=True)

        outPath = "%s/%s/%s/parc/%s_space-nativepro_T1w_atlas-subcortical.nii.gz"%(out,sub,ses,sbids)
        refPath = "%s/%s/%s/anat/%s_space-nativepro_T1w.nii.gz"%(out,sub,ses,sbids)
        figPath = "%s/nativepro_T1w_subcortical_screenshot.png"%(tmpDir)
        _static_block += nifti_check(outName="T1w nativepro subcortical atlas", outPath=outPath, refPath=refPath, figPath=figPath, roi=True)

        # Parcellations
        _static_block += (
            '<p style="font-family:Helvetica, sans-serif;font-size:10px;text-align:Left;margin-bottom:0px">'
            '<b> Parcellations </b> </p>'
        )

        parcellation_table = (
            '<table style="border:1px solid #666;width:100%">'
                '<tr><td style=padding-top:4px;padding-left:3px;text-align:center>Parcellation</td>'
                '<td style=padding-top:4px;padding-left:3px;text-align:center>Surface labels</td></tr>'
        )

        label_dir = "%s/%s/%s/label/"%(derivatives,recon,sbids)
        atlas = glob.glob(label_dir + 'lh.*_mics.annot', recursive=True)
        atlas = sorted([f.replace(label_dir, '').replace('.annot','').replace('lh.','') for f in atlas])
        for annot in atlas:
            fig = sbids + "_atlas-" + annot + "_desc-surf.png"
            fileL= "%s/lh.%s.annot"%(label_dir,annot)
            fileR= "%s/rh.%s.annot"%(label_dir,annot)
            figPath = tmpDir + '/' + fig
            label = np.concatenate((nb.freesurfer.read_annot(fileL)[0], nb.freesurfer.read_annot(fileR)[0]), axis=0)
            if os.path.exists(fileL) and os.path.exists(fileR):
                plot_hemispheres(surf_lh, surf_rh, array_name=label, size=(900, 250), zoom=1.25, embed_nb=True, interactive=False, share='both',
                                 nan_color=(0, 0, 0, 1), cmap=cmap_gradient(len(np.unique(label)), ['inferno', 'hsv', 'hsv', 'tab20b']), transparent_bg=False,
                                 screenshot = True, filename = figPath)

            parcellation_table += (
                '<tr><td style=padding-top:4px;padding-bottom:4px;padding-left:3px;padding-right:4px;text-align:left>{annot}</td>'
                '<td style=padding-top:4px;padding-bottom:4px;padding-left:3px;padding-right:3px;text-align:center><img style="display:block;width:1500px%;margin-top:0px" src="{figPath}"></td></tr>'
            ).format(annot=annot,figPath=figPath)

        parcellation_table += "</table>"

        _static_block += parcellation_table

        # Surfaces
        _static_block += (
            '<p style="font-family:Helvetica, sans-serif;font-size:10px;text-align:Left;margin-bottom:0px">'
            '<b> Surfaces </b> </p>'
        )

        surf_dir = "%s/%s/%s/surf/"%(out,sub,ses)
        for surf in ['fsnative', 'fsaverage5', 'fsLR-32k', 'fsLR-5k']:
            lhM, rhM = load_surface(surf_dir+sbids+'_hemi-L_space-nativepro_surf-'+surf+'_label-midthickness.surf.gii',
                                    surf_dir+sbids+'_hemi-R_space-nativepro_surf-'+surf+'_label-midthickness.surf.gii', with_normals=True, join=False)
            lhP, rhP = load_surface(surf_dir+sbids+'_hemi-L_space-nativepro_surf-'+surf+'_label-pial.surf.gii',
                                    surf_dir+sbids+'_hemi-R_space-nativepro_surf-'+surf+'_label-pial.surf.gii', with_normals=True, join=False)
            lhW, rhW = load_surface(surf_dir+sbids+'_hemi-L_space-nativepro_surf-'+surf+'_label-white.surf.gii',
                                    surf_dir+sbids+'_hemi-R_space-nativepro_surf-'+surf+'_label-white.surf.gii', with_normals=True, join=False)
            Val = np.repeat(0, lhM.n_points + rhM.n_points, axis=0)
            grey = plt.colors.ListedColormap(np.full((256, 4), [0.65, 0.65, 0.65, 1]))

            # Sphere native
            plot_hemispheres(lhM, rhM, array_name=Val, size=(900, 250), zoom=1.25, embed_nb=True, interactive=False, share='both',
                             nan_color=(0, 0, 0, 1), color_range=(-1,1), cmap=grey, transparent_bg=False,
                             screenshot = True, filename = tmpDir + '/' + sbids + '_space-nativepro_surf-' + surf + '_label-midthickness.png')
            plot_hemispheres(lhP, rhP, array_name=Val, size=(900, 250), zoom=1.25, embed_nb=True, interactive=False, share='both',
                             nan_color=(0, 0, 0, 1), color_range=(1.5, 4), cmap=grey, transparent_bg=False,
                             screenshot = True, filename = tmpDir + '/' + sbids + '_space-nativepro_surf-' + surf + '_label-pial.png')
            plot_hemispheres(lhW, rhW, array_name=Val, size=(900, 250), zoom=1.25, embed_nb=True, interactive=False, share='both',
                             nan_color=(0, 0, 0, 1), color_range=(1.5, 4), cmap=grey, transparent_bg=False,
                             screenshot = True, filename = tmpDir + '/' + sbids + '_space-nativepro_surf-' + surf + '_label-white.png')

            surface_table = (
                '<table style="border:1px solid #666;width:100%">'
                     '<tr><td style=padding-top:4px;padding-left:3px;padding-right:4px;text-align:center colspan="2">{surf}</td></tr>'
                     # Pial
                     '<tr><td style=padding-top:4px;padding-bottom:4px;padding-left:3px;padding-right:4px;text-align:left>Pial surface</td>'
                     '<td style=padding-top:4px;padding-bottom:4px;padding-left:3px;padding-right:3px;text-align:center><img style="display:block;width:1500px%;margin-top:0px" src="{pPath}"></td></tr>'
                     # Middle
                     '<tr><td style=padding-top:4px;padding-bottom:4px;padding-left:3px;padding-right:4px;text-align:left>Middle surface</td>'
                     '<td style=padding-top:4px;padding-bottom:4px;padding-left:3px;padding-right:3px;text-align:center><img style="display:block;width:1500px%;margin-top:0px" src="{mPath}"></td></tr>'
                     # White
                     '<tr><td style=padding-top:4px;padding-bottom:4px;padding-left:3px;padding-right:4px;text-align:left>White surface</td>'
                     '<td style=padding-top:4px;padding-bottom:4px;padding-left:3px;padding-right:3px;text-align:center><img style="display:block;width:1500px%;margin-top:0px" src="{wPath}"></td></tr>'
                '</table>'
            )

            _static_block += surface_table.format(surf=surf,
                pPath=tmpDir+'/'+sbids+'_space-nativepro_surf-'+surf+'_label-pial.png',
                mPath=tmpDir+'/'+sbids+'_space-nativepro_surf-'+surf+'_label-midthickness.png',
                wPath=tmpDir+'/'+sbids+'_space-nativepro_surf-'+surf+'_label-white.png'
            )

        # Morphological outputs:
        _static_block += (
            '<p style="font-family:Helvetica, sans-serif;font-size:10px;text-align:Left;margin-bottom:0px">'
            '<b> Morphological features </b> </p>'
        )

        fs5I_lh = read_surface(surfaceDir+'/fsaverage5/surf/lh.inflated', itype='fs')
        fs5I_rh = read_surface(surfaceDir+'/fsaverage5/surf/rh.inflated', itype='fs')

        global c69I_lh, c69I_rh
        c69I_lh = read_surface(MICAPIPE+'/surfaces/lh.conte69.inflated.gii', itype='gii')
        c69I_rh = read_surface(MICAPIPE+'/surfaces/rh.conte69.inflated.gii', itype='gii')

        for feature in ['curv', 'thickness']:

            feature_title = 'Curvature' if feature=='curv' else 'Thickness'
            feature_cmap = ColCurv if feature=='curv' else 'inferno'
            feature_crange = (-0.2, 0.2) if feature=='curv' else (1.5,4)

            feature_fsn_lh = "%s/%s/%s/maps/%s_hemi-L_surf-fsnative_label-%s.func.gii"%(out,sub,ses,sbids,feature)
            feature_fsn_rh = "%s/%s/%s/maps/%s_hemi-R_surf-fsnative_label-%s.func.gii"%(out,sub,ses,sbids,feature)
            feature_fsn_png = "%s/%s_surf-fsnative_label-%s.png"%(tmpDir,sbids,feature)
            f = np.concatenate((nb.load(feature_fsn_lh).darrays[0].data, nb.load(feature_fsn_rh).darrays[0].data), axis=0)
            plot_hemispheres(inf_lh, inf_rh, array_name=f, size=(900, 250), color_bar='bottom', zoom=1.25, embed_nb=True, interactive=False, share='both',
                             nan_color=(0, 0, 0, 1), color_range=feature_crange, cmap=feature_cmap, transparent_bg=False,
                             screenshot = True, filename = feature_fsn_png)

            feature_fs5_lh = "%s/%s/%s/maps/%s_hemi-L_surf-fsaverage5_label-%s.func.gii"%(out,sub,ses,sbids,feature)
            feature_fs5_rh = "%s/%s/%s/maps/%s_hemi-R_surf-fsaverage5_label-%s.func.gii"%(out,sub,ses,sbids,feature)
            feature_fs5_png = "%s/%s_surf-fsaverage5_label-%s.png"%(tmpDir,sbids,feature)
            f = np.concatenate((nb.load(feature_fs5_lh).darrays[0].data, nb.load(feature_fs5_rh).darrays[0].data), axis=0)
            plot_hemispheres(fs5I_lh, fs5I_rh, array_name=f, size=(900, 250), color_bar='bottom', zoom=1.25, embed_nb=True, interactive=False, share='both',
                             nan_color=(0, 0, 0, 1), color_range=feature_crange, cmap=feature_cmap, transparent_bg=False,
                             screenshot = True, filename = feature_fs5_png)

            feature_c69_5k_lh = "%s/%s/%s/maps/%s_hemi-L_surf-fsLR-5k_label-%s.func.gii"%(out,sub,ses,sbids,feature)
            feature_c69_5k_rh = "%s/%s/%s/maps/%s_hemi-R_surf-fsLR-5k_label-%s.func.gii"%(out,sub,ses,sbids,feature)
            feature_c69_5k_png = "%s/%s_surf-fsLR-5k_label-%s.png"%(tmpDir,sbids,feature)
            f = np.concatenate((nb.load(feature_c69_5k_lh).darrays[0].data, nb.load(feature_c69_5k_rh).darrays[0].data), axis=0)
            plot_hemispheres(c69I_lh, c69I_rh, array_name=f, size=(900, 250), color_bar='bottom', zoom=1.25, embed_nb=True, interactive=False, share='both',
                             nan_color=(0, 0, 0, 1), color_range=feature_crange, cmap=feature_cmap, transparent_bg=False,
                             screenshot = True, filename = feature_c69_5k_png)

            feature_c69_32k_lh = "%s/%s/%s/maps/%s_hemi-L_surf-fsLR-32k_label-%s.func.gii"%(out,sub,ses,sbids,feature)
            feature_c69_32k_rh = "%s/%s/%s/maps/%s_hemi-R_surf-fsLR-32k_label-%s.func.gii"%(out,sub,ses,sbids,feature)
            feature_c69_32k_png = "%s/%s_surf-fsLR-32k_label-%s.png"%(tmpDir,sbids,feature)
            f = np.concatenate((nb.load(feature_c69_32k_lh).darrays[0].data, nb.load(feature_c69_32k_rh).darrays[0].data), axis=0)
            plot_hemispheres(c69I_lh, c69I_rh, array_name=f, size=(900, 250), color_bar='bottom', zoom=1.25, embed_nb=True, interactive=False, share='both',
                             nan_color=(0, 0, 0, 1), color_range=feature_crange, cmap=feature_cmap, transparent_bg=False,
                             screenshot = True, filename = feature_c69_32k_png)

            morph_table = '<br />' if feature == 'thickness' else ''
            morph_table += (
                '<table style="border:1px solid #666;width:100%">'
                     '<tr><td style=padding-top:4px;padding-left:3px;padding-right:4px;text-align:center colspan="2">{feature_title}</td></tr>'
                     # Fsnative
                     '<tr><td style=padding-top:4px;padding-bottom:4px;padding-left:3px;padding-right:4px;text-align:left>Fsnative</td>'
                     '<td style=padding-top:4px;padding-bottom:4px;padding-left:3px;padding-right:3px;text-align:center><img style="display:block;width:1500px%;margin-top:0px" src="{feature_fsn_png}"></td></tr>'
                     # Fsaverage5
                     '<tr><td style=padding-top:4px;padding-bottom:4px;padding-left:3px;padding-right:4px;text-align:left>Fsaverage5</td>'
                     '<td style=padding-top:4px;padding-bottom:4px;padding-left:3px;padding-right:3px;text-align:center><img style="display:block;width:1500px%;margin-top:0px" src="{feature_fs5_png}"></td></tr>'
                     # fsLR-5k
                     '<tr><td style=padding-top:4px;padding-bottom:4px;padding-left:3px;padding-right:4px;text-align:left>FsLR (5k)</td>'
                     '<td style=padding-top:4px;padding-bottom:4px;padding-left:3px;padding-right:3px;text-align:center><img style="display:block;width:1500px%;margin-top:0px" src="{feature_c69_5k_png}"></td></tr>'
                     # fsLR-32k
                     '<tr><td style=padding-top:4px;padding-bottom:4px;padding-left:3px;padding-right:4px;text-align:left>FsLR (32k)</td>'
                     '<td style=padding-top:4px;padding-bottom:4px;padding-left:3px;padding-right:3px;text-align:center><img style="display:block;width:1500px%;margin-top:0px" src="{feature_c69_32k_png}"></td></tr>'
                '</table>'
            )

            _static_block += morph_table.format(feature_title=feature_title,
                feature_fsn_png=feature_fsn_png,
                feature_fs5_png=feature_fs5_png,
                feature_c69_5k_png=feature_c69_5k_png,
                feature_c69_32k_png=feature_c69_32k_png
            )

        return _static_block

## ---------------------------- PROC_FUNC MODULE --------------------------- ##
def qc_proc_dwi(proc_dwi_json=''):

    if check_json_exist_complete(proc_dwi_json):
        print('hi')

## ---------------------------- PROC_FUNC MODULE --------------------------- ##
def qc_proc_func(proc_func_json=''):

    tag = proc_func_json.split('%s_module-proc_func-desc-'%(sbids))[1].split('.json')[0]

    if check_json_exist_complete(proc_func_json):

        # QC header
        _static_block = qc_header()
        _static_block +=  report_module_header_template(module='proc_func (%s)'%(tag))

        # QC summary
        _static_block += report_qc_summary_template(proc_func_json)

        func_clean_json = glob.glob("%s/%s/%s/func/desc-%s/volumetric/%s_space-func_desc*_clean.json"%(out,sub,ses,tag,sbids))[0]
        with open( func_clean_json ) as f:
            func_clean_json = json.load(f)
        acquisition = func_clean_json["Acquisition"]

        # Inputs
        _static_block += (
                '<p style="font-family:Helvetica, sans-serif;font-size:12px;text-align:Left;margin-bottom:0px">'
                '<b>Inputs</b> </p>'
        )

        mainScan = func_clean_json["Preprocess"]["MainScan"].split()
        for i, s in enumerate(mainScan):
            outPath = tmpDir + '/' + s.split("%s/%s/%s/func/"%(bids,sub,ses))[1].split('.nii.gz')[0] + '_mean.nii.gz'
            outName = "Main scan (mean)" if len(mainScan) == 1 else "Main scan - echo %s (mean)"%(i+1)
            figPath = "%s/fmri_mainScan%s.png"%(tmpDir,i+1)
            _static_block += nifti_check(outName=outName, outPath=outPath, figPath=figPath)

        mainPhaseScan = func_clean_json["Preprocess"]["MainPhaseScan"]
        outPath = tmpDir + '/' + mainPhaseScan.split('%s/%s/%s/fmap/'%(bids,sub,ses))[1].split('.nii.gz')[0] + '_mean.nii.gz'
        figPath = "%s/fmri_mainPhaseScan.png"%(tmpDir)
        _static_block += nifti_check(outName="Main phase scan (mean)", outPath=outPath, figPath=figPath)

        reversePhaseScan = func_clean_json["Preprocess"]["ReversePhaseScan"]
        outPath = tmpDir + '/' + reversePhaseScan.split('%s/%s/%s/fmap/'%(bids,sub,ses))[1].split('.nii.gz')[0] + '_mean.nii.gz'
        figPath = "%s/fmri_reveresePhaseScan.png"%(tmpDir)
        _static_block += nifti_check(outName="Reverse phase scan (mean)", outPath=outPath, figPath=figPath)

        # Outputs
        _static_block += (
                '<p style="font-family:Helvetica, sans-serif;font-size:12px;text-align:Left;margin-bottom:0px">'
                '<b>Main outputs</b> </p>'
        )

        outPath = "%s/%s/%s/func/desc-%s/volumetric/%s_space-func_desc-%s_brain.nii.gz"%(out,sub,ses,tag,sbids,acquisition)
        figPath = "%s/func_brain_screenshot.png"%(tmpDir)
        _static_block += nifti_check(outName="fMRI brain", outPath=outPath, figPath=figPath)

        outPath = "%s/%s/%s/xfm/%s_from-%s_to-fsnative_bbr_mode-image_desc-bbregister.nii.gz"%(out,sub,ses,sbids,tag)
        refPath = "%s/%s/%s/anat/%s_space-fsnative_T1w.nii.gz"%(out,sub,ses,sbids)
        figPath = "%s/fmri_fsnative_screenshot.png"%(tmpDir)
        _static_block += nifti_check(outName="Registration: fMRI in %s native space"%(recon), outPath=outPath, refPath=refPath, figPath=figPath)

        outPath = "%s/%s/%s/anat/%s_space-nativepro_desc-%s_mean.nii.gz"%(out,sub,ses,sbids,tag)
        refPath = "%s/%s/%s/anat/%s_space-nativepro_T1w.nii.gz"%(out,sub,ses,sbids)
        figPath = "%s/fmri_nativepro_screenshot.png"%(tmpDir)
        _static_block += nifti_check(outName="Registration: fMRI in T1w nativepro space", outPath=outPath, refPath=refPath, figPath=figPath)

        outPath = "%s/%s/%s/func/desc-%s/volumetric/%s_space-func_desc-T1w.nii.gz"%(out,sub,ses,tag,sbids)
        refPath = "%s/%s/%s/func/desc-%s/volumetric/%s_space-func_desc-%s_brain.nii.gz"%(out,sub,ses,tag,sbids,acquisition)
        figPath = "%s/nativepro_T1w_fmri_screenshot.png"%(tmpDir)
        _static_block += nifti_check(outName="Registration: T1w nativepro in fMRI space", outPath=outPath, refPath=refPath, figPath=figPath)

        outPath = "%s/%s/%s/func/desc-%s/volumetric/%s_space-func_desc-%s_cerebellum.nii.gz"%(out,sub,ses,tag,sbids,acquisition)
        refPath = "%s/%s/%s/func/desc-%s/volumetric/%s_space-func_desc-%s_brain.nii.gz"%(out,sub,ses,tag,sbids,acquisition)
        figPath = "%s/fMRI_cerebellum_screenshot.png"%(tmpDir)
        _static_block += nifti_check(outName="Cerebellum atlas in fMRI space", outPath=outPath, refPath=refPath, figPath=figPath, roi=True)

        outPath = "%s/%s/%s/func/desc-%s/volumetric/%s_space-func_desc-%s_subcortical.nii.gz"%(out,sub,ses,tag,sbids,acquisition)
        refPath = "%s/%s/%s/func/desc-%s/volumetric/%s_space-func_desc-%s_brain.nii.gz"%(out,sub,ses,tag,sbids,acquisition)
        figPath = "%s/fMRI_subcortical_screenshot.png"%(tmpDir)
        _static_block += nifti_check(outName="Subcortical atlas in fMRI space", outPath=outPath, refPath=refPath, figPath=figPath, roi=True)

        outPath = "%s/%s/%s/func/desc-%s/volumetric/%s_space-func_desc-%s_framewiseDisplacement.png"%(out,sub,ses,tag,sbids,acquisition)
        _static_block += report_module_output_template(outName='Framewise displace: fMRI', outPath=outPath, figPath=outPath)

        _static_block += (
                '<p style="font-family:Helvetica, sans-serif;font-size:12px;text-align:Left;margin-bottom:0px">'
                '<b>Functional connectomes</b> </p>'
        )

        fc_connectome_table = (
            '<table style="border:1px solid #666;width:100%">'
                '<tr><td style=padding-top:4px;padding-left:3px;text-align:center><b>Parcellation<b></td>'
                '<td style=padding-top:4px;padding-left:3px;text-align:center><b>Connectome<b></td>'
                '<td style=padding-top:4px;padding-left:3px;text-align:center>Degree</td></tr>'
        )

        label_dir = "%s/%s/%s/label/"%(derivatives,recon,sbids)
        atlas = glob.glob(label_dir + 'lh.*_mics.annot', recursive=True)
        atlas = sorted([f.replace(label_dir, '').replace('.annot','').replace('lh.','').replace('_mics','') for f in atlas])
        for annot in atlas:
            # fc connectomes
            fc_fig = tmpDir + "/" + sbids + "space-conte69-32k_atlas-" + annot + "_fc.png"
            fc_file = "%s/%s/%s/func/desc-%s/surf/%s_atlas-%s_desc-FC.txt"%(out,sub,ses,tag,sbids,annot)

            if os.path.isfile(fc_file):

                fc_mtx = np.loadtxt(fc_file, dtype=float, delimiter=' ')
                fc = fc_mtx[49:, 49:]
                np.seterr(divide='ignore')
                fcz = np.arctanh(fc)
                fcz[~np.isfinite(fcz)] = 0
                fcz = np.triu(fcz,1)+fcz.T
                pltpy.imshow(fcz, cmap="Reds", aspect='auto')
                pltpy.savefig(fc_fig)

                # Degree
                deg_fig = tmpDir + "/" + sbids + "_atlas-" + annot + "_fc_degree.png"
                fc_pos = np.copy(fcz)
                fc_pos[0>fc_pos] = 0
                deg = np.sum(fc_pos,axis=1)

                annot_file = MICAPIPE + '/parcellations/' + annot + '_conte69.csv'
                if os.path.isfile(annot_file):
                    labels_c69 = np.loadtxt(open(annot_file), dtype=int)
                    mask_c69 = labels_c69 != 0

                    deg_surf = map_to_labels(deg, labels_c69, fill=np.nan, mask=mask_c69)
                    plot_hemispheres(c69I_lh, c69I_rh, array_name=deg_surf, size=(900, 750), color_bar='bottom', zoom=1.25, embed_nb=True, interactive=False, share='both',
                                     nan_color=(0, 0, 0, 1), cmap='Reds', layout_style='grid', transparent_bg=False,
                                     screenshot = True, filename = deg_fig)
                    fc_connectome_table += (
                        '<tr><td style=padding-top:4px;padding-bottom:4px;padding-left:3px;padding-right:4px;text-align:center>{annot}</td>'
                        '<td style=padding-top:4px;padding-bottom:4px;padding-left:3px;padding-right:3px;text-align:center><img style="display:block;width:1500px%;margin-top:0px" src="{fc_fig}"></td>'
                        '<td style=padding-top:4px;padding-bottom:4px;padding-left:3px;padding-right:3px;text-align:center><img style="display:block;width:1500px%;margin-top:0px" src="{deg_fig}"></td></tr>'
                    ).format(annot=annot,fc_fig=fc_fig,deg_fig=deg_fig)

        fc_connectome_table += "</table>"

        _static_block += fc_connectome_table

        return _static_block

## ------------------------------- SC MODULE ------------------------------ ##
def qc_sc(sc_json=''):

    if check_json_exist_complete(sc_json):

        streamlines = sc_json.split('%s_module-SC-'%(sbids))[1].split('.json')[0]

        # QC header
        _static_block = qc_header()
        _static_block +=  report_module_header_template(module="Structural connectomes (%s streamlines)"%(streamlines))

        # QC summary
        _static_block += report_qc_summary_template(sc_json)

        tdi_json = os.path.realpath("%s/%s/%s/dwi/%s_space-dwi_desc-iFOD2-%s_tractography.json"%(out,sub,ses,sbids,streamlines))
        with open( tdi_json ) as f:
            tdi_json = json.load(f)

        # Inputs
        _static_block += (
                '<p style="font-family:Helvetica, sans-serif;font-size:12px;text-align:Left;margin-bottom:0px">'
                '<b>Inputs</b> </p>'
        )

        dti_fod = tdi_json["fileInfo"]["Name"]
        outPath = tmpDir + '/' + dti_fod.split("%s/%s/%s/dwi/"%(out,sub,ses))[1].split('.mif')[0] + '.nii.gz'
        figPath = "%s/dti_FOD.png"%(tmpDir)
        _static_block += nifti_check(outName="Fiber orientation distribution", outPath=outPath, figPath=figPath)

        # Outputs
        _static_block += (
                '<p style="font-family:Helvetica, sans-serif;font-size:12px;text-align:Left;margin-bottom:0px">'
                '<b>Main outputs</b> </p>'
        )

        tractography = tdi_json["Tractography"]
        tractography_table = (
                '<table style="border:1px solid #666;width:100%">'
                    '<tr><td style=padding-top:4px;padding-left:3px;padding-right:4px;text-align:center colspan="2">Tractography information</td></tr>'
        )
        for k in tractography:
            tractography_table += (
                '<tr><td style=padding-top:4px;padding-bottom:4px;padding-left:3px;padding-right:4px;text-align:left;width:20%>{left}</td>'
                '<td style=padding-top:4px;padding-bottom:4px;padding-left:3px;padding-right:3px;text-align:left>{right}</td></tr>'
            ).format(left=k, right=tractography[k])
        tractography_table += "</table>"

        _static_block += tractography_table

        outPath = "%s/%s_space-dwi_desc-iFOD2-%s_tdi_mean.nii.gz"%(tmpDir,sbids,streamlines)
        figPath = "%s/tdi_%s.png"%(tmpDir,streamlines)
        _static_block += nifti_check(outName="Track density imaging (%s tracks)"%(streamlines), outPath=outPath, figPath=figPath)

        label_dir = "%s/%s/%s/label/"%(derivatives,recon,sbids)
        atlas = glob.glob(label_dir + 'lh.*_mics.annot', recursive=True)
        atlas = sorted([f.replace(label_dir, '').replace('.annot','').replace('lh.','').replace('_mics','') for f in atlas])

        connectomes = ['full-connectome', 'full-edgeLengths'] if tractography["weighted_SC"] == False else ['full-connectome', 'full-edgeLengths', 'full-weighted_connectome']
        sc_connectome_table = el_connectome_table = wsc_connectome_table = ''
        for connectomeType in connectomes:

            connectome_table = (
                '<table style="border:1px solid #666;width:100%">'
                    '<tr><td style=padding-top:4px;padding-left:3px;text-align:center><b>Parcellation</b></td>'
                    '<td style=padding-top:4px;padding-left:3px;text-align:center><b>Full connectomes</b></td>'
                    '<td style=padding-top:4px;padding-left:3px;text-align:center><b>Degree</b></td></tr>'
            )

            for annot in atlas:

                c_fig = tmpDir + "/" + sbids + "space-dwi_atlas-" + annot + "_desc-iFOD2-" + streamlines + "SIFT2_" + connectomeType + ".png"
                c_file = "%s/%s/%s/dwi/connectomes/%s_space-dwi_atlas-%s_desc-iFOD2-%s-SIFT2_%s.txt"%(out,sub,ses,sbids,annot,streamlines,connectomeType)
                c = np.loadtxt(c_file, dtype=float, delimiter=' ')
                c = np.log(np.triu(c,1)+c.T)
                c[np.isneginf(c)] = 0
                c[c==0] = np.finfo(float).eps
                pltpy.imshow(c, cmap="Purples", aspect='auto')
                pltpy.savefig(c_fig)

                deg_fig = tmpDir + "/" + sbids + "space-dwi_atlas-" + annot + "_desc-iFOD2-" + streamlines + "SIFT2_" + connectomeType + "_degree.png"
                deg = np.sum(c[49:,49:],axis=1)

                annot_file = MICAPIPE + '/parcellations/' + annot + '_conte69.csv'
                if os.path.isfile(annot_file):
                    labels_c69 = np.loadtxt(open(annot_file), dtype=int)
                    mask_c69 = labels_c69 != 0

                    deg_surf = map_to_labels(deg, labels_c69, fill=np.nan, mask=mask_c69)
                    plot_hemispheres(c69I_lh, c69I_rh, array_name=deg_surf, size=(900, 750), color_bar='bottom', zoom=1.25, embed_nb=True, interactive=False, share='both',
                                     nan_color=(0, 0, 0, 1), color_range='sym', cmap='Purples', layout_style='grid', transparent_bg=False,
                                     screenshot = True, filename = deg_fig)
                    connectome_table += (
                        '<tr><td style=padding-top:4px;padding-bottom:4px;padding-left:3px;padding-right:4px;text-align:center>{annot}</td>'
                        '<td style=padding-top:4px;padding-bottom:4px;padding-left:3px;padding-right:3px;text-align:center><img style="display:block;width:1500px%;margin-top:0px" src="{c_fig}"></td>'
                        '<td style=padding-top:4px;padding-bottom:4px;padding-left:3px;padding-right:3px;text-align:center><img style="display:block;width:1500px%;margin-top:0px" src="{deg_fig}"></td></tr>'
                    ).format(annot=annot,c_fig=c_fig,deg_fig=deg_fig)

            connectome_table += "</table>"

            if connectomeType == 'full-connectome':
                sc_connectome_table += connectome_table
            elif connectomeType == 'full-edgeLengths':
                el_connectome_table += connectome_table
            elif connectomeType == 'full-weighted_connectome':
                wsc_connectome_table += connectome_table

        _static_block += (
                '<p style="font-family:Helvetica, sans-serif;font-size:12px;text-align:Left;margin-bottom:0px">'
                '<b>Structural connectomes ({streamlines})</b> </p>'
        ).format(streamlines=streamlines)
        _static_block += sc_connectome_table

        _static_block += (
                '<p style="font-family:Helvetica, sans-serif;font-size:12px;text-align:Left;margin-bottom:0px">'
                '<b>Edge length connectomes ({streamlines})</b> </p>'
        ).format(streamlines=streamlines)
        _static_block += el_connectome_table

        _static_block += (
                '<p style="font-family:Helvetica, sans-serif;font-size:12px;text-align:Left;margin-bottom:0px">'
                '<b>Weighted structural connectomes ({streamlines})</b> </p>'
        ).format(streamlines=streamlines)
        _static_block += wsc_connectome_table

        return _static_block

## ------------------------------- MPC MODULE ------------------------------ ##
def qc_mpc(mpc_json=''):

    if check_json_exist_complete(mpc_json):
        acquisition = mpc_json.split('%s_module-MPC-'%(sbids))[1].split('.json')[0]

        # QC header
        _static_block = qc_header()
        _static_block +=  report_module_header_template(module='Microstructural profile covariance (%s)'%(acquisition))

        # QC summary
        _static_block += report_qc_summary_template(mpc_json)

        # Inputs:
        _static_block += (
                '<p style="font-family:Helvetica, sans-serif;font-size:12px;text-align:Left;margin-bottom:0px">'
                '<b>Main inputs:</b> </p>'
        )

        proc_mpc_json = os.path.realpath("%s/%s/%s/mpc/acq-%s/%s_MPC-%s.json"%(out,sub,ses,acquisition,sbids,acquisition))
        with open( proc_mpc_json ) as f:
            mpc_description = json.load(f)
        microstructural_img = mpc_description["microstructural_img"]
        microstructural_reg = mpc_description["microstructural_reg"]

        outPath = microstructural_img
        figPath = "%s/%s_microstructural_img.png"%(tmpDir,acquisition)
        _static_block += nifti_check(outName="Microstructural image", outPath=outPath, figPath=figPath)

        outPath = microstructural_reg
        figPath = "%s/%s_microstructural_reg.png"%(tmpDir,acquisition)
        _static_block += nifti_check(outName="Microstructural registration", outPath=outPath, figPath=figPath)

        # Outputs
        _static_block += (
                '<p style="font-family:Helvetica, sans-serif;font-size:12px;text-align:Left;margin-bottom:0px">'
                '<b>Main outputs</b> </p>'
        )

        surfaceTransform = mpc_description["surfaceTransformation"]
        _static_block += (
            '<table style="border:1px solid #666;width:100%">'
                # Acquisition
                '<tr><td style=padding-top:4px;padding-left:3px;text-align:left;width:20%>Acquisition</td>'
                '<td style=padding-top:4px;padding-left:3px;text-align:left>{acquisition}</td></tr>'
                # Surface Transformation
                '<tr><td style=padding-top:4px;padding-left:3px;text-align:left>Surface transformation</td>'
                '<td style=padding-top:4px;padding-left:3px;text-align:left>{surfaceTransform}</td></tr>'
            '</table>'
        ).format(acquisition=acquisition,surfaceTransform=surfaceTransform)

        outPath = "%s/%s/%s/anat/%s_space-fsnative_T1w.nii.gz"%(out,sub,ses,sbids)
        refPath = "%s/%s/%s/anat/%s_space-fsnative_desc-%s.nii.gz"%(out,sub,ses,sbids,acquisition)
        figPath = "%s/%s_fsnative_screenshot.png"%(tmpDir,acquisition)
        _static_block += nifti_check(outName="Registration: %s in %s native space"%(acquisition,recon), outPath=outPath, refPath=refPath, figPath=figPath)

        _static_block += (
                '<p style="font-family:Helvetica, sans-serif;font-size:12px;text-align:Left;margin-bottom:0px">'
                '<b>MPC connectomes</b> </p>'
        )

        mpc_connectome_table = (
            '<table style="border:1px solid #666;width:100%">'
                '<tr><td style=padding-top:4px;padding-left:3px;text-align:center><b>Parcellation</b></td>'
                '<td style=padding-top:4px;padding-left:3px;text-align:center><b>Intensity profiles</b></td>'
                '<td style=padding-top:4px;padding-left:3px;text-align:center><b>Connectomes</b></td>'
                '<td style=padding-top:4px;padding-left:3px;text-align:center><b>Degree</b></td></tr>'
        )


        label_dir = "%s/%s/%s/label/"%(derivatives,recon,sbids)
        atlas = glob.glob(label_dir + 'lh.*_mics.annot', recursive=True)
        atlas = sorted([f.replace(label_dir, '').replace('.annot','').replace('lh.','').replace('_mics','') for f in atlas])
        for annot in atlas:

            # Intensity profiles
            ip_fig = tmpDir + "/" + sbids + "space-fsnative_atlas-" + annot + "_desc-" + acquisition + "_intensity_profiles.png"
            ip_file = "%s/%s/%s/mpc/acq-%s/%s_space-fsnative_atlas-%s_desc-intensity_profiles.txt"%(out,sub,ses,acquisition,sbids,annot)
            ip = np.loadtxt(ip_file, dtype=float, delimiter=' ')
            pltpy.imshow(ip, cmap="Greens", aspect='auto')
            pltpy.savefig(ip_fig)

            # MPC connectomes
            mpc_fig = tmpDir + "/" + sbids + "space-fsnative_atlas-" + annot + "_desc-" + acquisition + "_mpc.png"
            mpc_file = "%s/%s/%s/mpc/acq-%s/%s_space-fsnative_atlas-%s_desc-MPC.txt"%(out,sub,ses,acquisition,sbids,annot)
            mpc = np.loadtxt(mpc_file, dtype=float, delimiter=' ')
            mpc = np.triu(mpc,1)+mpc.T
            mpc = np.delete(np.delete(mpc, 0, axis=0), 0, axis=1)
            mpc[~np.isfinite(mpc)] = np.finfo(float).eps
            mpc[mpc==0] = np.finfo(float).eps

            pltpy.imshow(mpc, cmap="Greens", aspect='auto')
            pltpy.savefig(mpc_fig)

            # Degree
            deg_fig = tmpDir + "/" + sbids + "space-fsnative_atlas-" + annot + "_desc-" + acquisition + "_mpc_degree.png"
            deg = np.sum(mpc,axis=1)

            annot_file = MICAPIPE + '/parcellations/' + annot + '_conte69.csv'
            if os.path.isfile(annot_file):
                labels_c69 = np.loadtxt(open(annot_file), dtype=int)
                mask_c69 = labels_c69 != 0

                deg_surf = map_to_labels(deg, labels_c69, fill=np.nan, mask=mask_c69)
                plot_hemispheres(c69I_lh, c69I_rh, array_name=deg_surf, size=(900, 750), color_bar='bottom', zoom=1.25, embed_nb=True, interactive=False, share='both',
                                 nan_color=(0, 0, 0, 1), color_range='sym', cmap='Greens', layout_style='grid', transparent_bg=False,
                                 screenshot = True, filename = deg_fig)
                mpc_connectome_table += (
                    '<tr><td style=padding-top:4px;padding-bottom:4px;padding-left:3px;padding-right:4px;text-align:center>{annot}</td>'
                    '<td style=padding-top:4px;padding-bottom:4px;padding-left:3px;padding-right:3px;text-align:center><img style="display:block;width:1500px%;margin-top:0px" src="{ip_fig}"></td>'
                    '<td style=padding-top:4px;padding-bottom:4px;padding-left:3px;padding-right:3px;text-align:center><img style="display:block;width:1500px%;margin-top:0px" src="{mpc_fig}"></td>'
                    '<td style=padding-top:4px;padding-bottom:4px;padding-left:3px;padding-right:3px;text-align:center><img style="display:block;width:1500px%;margin-top:0px" src="{deg_fig}"></td></tr>'
                ).format(annot=annot,ip_fig=ip_fig,mpc_fig=mpc_fig,deg_fig=deg_fig)

        mpc_connectome_table += "</table>"

        _static_block += mpc_connectome_table

        return _static_block

## -------------------------------- GD MODULE ------------------------------ ##
def qc_gd(gd_json=''):

    if check_json_exist_complete(gd_json):

        # QC header
        _static_block = qc_header()
        _static_block +=  report_module_header_template(module='Geodesic distance')

        # QC summary
        _static_block += report_qc_summary_template(gd_json)

        # Outputs
        _static_block += (
                '<p style="font-family:Helvetica, sans-serif;font-size:12px;text-align:Left;margin-bottom:0px">'
                '<b>Main outputs</b> </p>'
        )

        _static_block += (
                '<p style="font-family:Helvetica, sans-serif;font-size:12px;text-align:Left;margin-bottom:0px">'
                '<b>GD connectomes</b> </p>'
        )

        gd_connectome_table = (
            '<table style="border:1px solid #666;width:100%">'
                '<tr><td style=padding-top:4px;padding-left:3px;text-align:center><b>Parcellation</b></td>'
                '<td style=padding-top:4px;padding-left:3px;text-align:center><b>Connectomes</b></td>'
                '<td style=padding-top:4px;padding-left:3px;text-align:center><b>Degree</b></td></tr>'
        )


        label_dir = "%s/%s/%s/label/"%(derivatives,recon,sbids)
        atlas = glob.glob(label_dir + 'lh.*_mics.annot', recursive=True)
        atlas = sorted([f.replace(label_dir, '').replace('.annot','').replace('lh.','').replace('_mics','') for f in atlas])
        for annot in atlas:

            # gd connectomes
            gd_fig = tmpDir + "/" + sbids + "space-fsnative_atlas-" + annot + "_gd.png"
            gd_file = "%s/%s/%s/dist/%s_space-fsnative_atlas-%s_GD.txt"%(out,sub,ses,sbids,annot)
            gd = np.loadtxt(gd_file, dtype=float, delimiter=' ')
            gd = np.delete(np.delete(gd, 0, axis=0), 0, axis=1)
            pltpy.imshow(gd, cmap="Blues", aspect='auto')
            pltpy.savefig(gd_fig)

            # Degree
            deg_fig = tmpDir + "/" + sbids + "space-fsnative_atlas-" + annot + "_gd_degree.png"
            deg = np.sum(gd,axis=1)

            annot_file = MICAPIPE + '/parcellations/' + annot + '_conte69.csv'
            if os.path.isfile(annot_file):
                labels_c69 = np.loadtxt(open(annot_file), dtype=int)
                mask_c69 = labels_c69 != 0

                deg_surf = map_to_labels(deg, labels_c69, fill=np.nan, mask=mask_c69)
                plot_hemispheres(c69I_lh, c69I_rh, array_name=deg_surf, size=(900, 750), color_bar='bottom', zoom=1.25, embed_nb=True, interactive=False, share='both',
                                 nan_color=(0, 0, 0, 1), cmap='Blues', layout_style='grid', transparent_bg=False,
                                 screenshot = True, filename = deg_fig)
                gd_connectome_table += (
                    '<tr><td style=padding-top:4px;padding-bottom:4px;padding-left:3px;padding-right:4px;text-align:center>{annot}</td>'
                    '<td style=padding-top:4px;padding-bottom:4px;padding-left:3px;padding-right:3px;text-align:center><img style="display:block;width:1500px%;margin-top:0px" src="{gd_fig}"></td>'
                    '<td style=padding-top:4px;padding-bottom:4px;padding-left:3px;padding-right:3px;text-align:center><img style="display:block;width:1500px%;margin-top:0px" src="{deg_fig}"></td></tr>'
                ).format(annot=annot,gd_fig=gd_fig,deg_fig=deg_fig)

        gd_connectome_table += "</table>"

        _static_block += gd_connectome_table

        return _static_block


# Utility function
def convert_html_to_pdf(source_html, output_filename):
    # open output file for writing (truncated binary)
    result_file = open(output_filename, "w+b")

    # convert HTML to PDF
    pisa_status = pisa.CreatePDF(
            source_html,                # the HTML to convert
            dest=result_file)           # file handle to recieve result

    # close output file
    result_file.close()                 # close output file

    # return True on success and False on errors
    return pisa_status.err

# Generate PDF report of Micapipe QC
qc_module_function = {
    #'modules':   ['proc_structural', 'proc_surf', 'post_structural', 'proc_func', 'SC', 'MPC', 'GD'],
    #'functions': [qc_proc_structural, qc_proc_surf, qc_post_structural, qc_proc_func, qc_sc, qc_mpc, qc_gd]
    'modules':   ['proc_surf', 'post_structural'],
    'functions': [qc_proc_surf, qc_post_structural]
}

for i, m in enumerate(qc_module_function['modules']):
    module_qc_json = glob.glob("%s/%s/%s/QC/%s_module-%s*.json"%(out,sub,ses,sbids,m))
    for j in module_qc_json:
        #try:
        static_report = qc_module_function['functions'][i](j)
        convert_html_to_pdf(static_report, j.replace('.json','_qc-report.pdf'))
        #except:
        #    print("[WARNING].... Some files are missing for %s module"%(m))
        #else:
        #    print("[INFO].... Generating QC pdf for %s module"%(m))
