#!/bin/bash
#
# T1w Structural processing with bash:
#
# Preprocessing workflow for structural T1w.
#
# This workflow makes use of FREESURFER, FSL (fslchfiletype)
#
# Atlas an templates are avaliable from:
#
# https://github.com/MICA-MNI/micaopen/templates
#
#   ARGUMENTS order:
#   $1 : BIDS directory
#   $2 : participant
#   $3 : Out parcDirectory
#
# FastSurfer
# https://doi.org/10.1016/j.neuroimage.2020.117012
# Github: https://github.com/Deep-MI/FastSurfer
BIDS=$1
id=$2
out=$3
SES=$4
nocleanup=$5
export threads=$6
tmpDir=$7
surfdir=$8
FastSurfer=$9
fs_licence=${10}
t1=${11}
PROC=${12}
here=$(pwd)
export OMP_NUM_THREADS=$threads

#------------------------------------------------------------------------------#
# qsub configuration
if [ "$PROC" = "qsub-MICA" ] || [ "$PROC" = "qsub-all.q" ];then
    export MICAPIPE=/data_/mica1/01_programs/micapipe-v0.2.0
    source "${MICAPIPE}/functions/init.sh" "$threads"
fi

# source utilities
source "$MICAPIPE/functions/utilities.sh"

# Assigns variables names
bids_variables "$BIDS" "$id" "$out" "$SES"

# Check inputs: Nativepro T1 or custom T1
if [[ "$t1" != "DEFAULT" ]]; then
    if [ ! -f "${t1}" ]; then Error "The provided T1 volume does not exist:\n\t${t1}"; exit; fi
    t1_2proc=${t1}
  else
    if [ ! -f "${T1nativepro}" ]; then Error "Subject $id doesn't have T1_nativepro"; exit; fi
    t1_2proc=${T1nativepro}
fi

# Surface Directory
if [[ "$FastSurfer" == "TRUE" ]]; then recon="fastsurfer"; else recon="freesurfer"; fi
set_surface_directory "${recon}"
Note "Surface software" "${recon}"

# Surface Directories
if [ ! -d "${dir_surf}" ]; then mkdir "${dir_surf}" && chmod -R 770 "${dir_surf}"; fi
if [ ! -L "${dir_surf}/fsaverage5" ]; then Do_cmd ln -s "$FREESURFER_HOME/subjects/fsaverage5/" "${dir_surf}"; fi
if [ ! -d "${dir_surf}/conte69" ]; then Do_cmd mkdir -p "${dir_surf}"/conte69/surf; cp ${MICAPIPE}/surfaces/*conte69.gii "${dir_surf}"/conte69/surf; fi

# End if module has been processed
module_json="${dir_QC}/${idBIDS}_module-proc_surf-${recon}.json"
if [ -f "${module_json}" ]; then
  status=$(grep "Status" "${module_json}" | awk -F '"' '{print $4}')
  if [ "$status" == "COMPLETED" ]; then
  Note "Proc_surf json" "${module_json}"
  Warning "Subject ${idBIDS} has been processed with -proc_surf
            If you want to re-run this step again, first erase all the outputs with:
            micapipe_cleanup -sub <subject_id> -out <derivatives> -bids <BIDS_dir> -proc_surf"; exit
  else
      Info "proc_surf is INCOMPLETE, processing will continute"
  fi
fi

#------------------------------------------------------------------------------#
Title "Surface processing\n\t\tmicapipe $Version, $PROC "
micapipe_software
# print the names on the terminal
bids_print.variables
Note "Preprocessed surface directory: $surfdir"

# # Create script specific temp directory
tmp="${tmpDir}/${id}_micapipe_proc-surf_${RANDOM}"
Info "Processing surfaces"
Note "Saving temporal dir:" "$nocleanup"
Note "Temporal dir:" "${tmp}"
Note "Parallel processing:" "$threads threads"
Note "fs licence:" "${fs_licence}"
Note "fastsurfer img:" "${fastsurfer_img}"
Note "t1 to process:" "${t1_2proc}"
Do_cmd mkdir -p "${tmp}/nii"

#	Timer and steps progress
aloita=$(date +%s)
N=0
Nsteps=0

# TRAP in case the script fails
trap 'cleanup $tmp $nocleanup $here' SIGINT SIGTERM

# IF SURFACE directory is provided create a symbolic link
if [[ "$surfdir" != "FALSE" ]]; then ((N++))
    if [[ -d "$surfdir" ]]; then
        if [[ -d "$dir_subjsurf" ]]; then
            # dir_subjsurf IS under ${out}/fastsurfer
            Info "Current surface directory has a compatible naming and structure with micapipe"
        else
            Info "Creating links for micapipe compatibility"
            # dir_subjsurf IS NOT at ${out}/fastsurfer
            Do_cmd ln -s "$surfdir" "$dir_subjsurf"
        fi
    elif [[ ! -d "$surfdir" ]]; then
        Error "The provided surface directory does not exist: $surfdir"
        cleanup $tmp $nocleanup $here; exit
    fi
    Do_cmd cp "${dir_subjsurf}/scripts/recon-all.log" "${dir_logs}/recon-all.log"

# If not, get ready to run the surface reconstruccion
elif [[ "$surfdir" == "FALSE" ]]; then ((N++))
    # Define SUBJECTS_DIR for surface processing as a global variable
    export SUBJECTS_DIR=${tmp} # Will work on a temporal directory
    t1="${SUBJECTS_DIR}/nii/${idBIDS}"_t1w.nii.gz
    Do_cmd cp "${t1_2proc}" "${t1}"

    # Recontruction method
    if [[ "$FastSurfer" == "TRUE" ]]; then
        Info "FastSurfer: running the singularity image"
        Do_cmd mkdir -p "${SUBJECTS_DIR}/${idBIDS}"

        singularity exec --nv -B "${SUBJECTS_DIR}/nii":/data \
                              -B "${SUBJECTS_DIR}":/output \
                              -B "${fs_licence}":/fs \
                              -B "${tmp}/nii":/anat \
                               "${fastsurfer_img}" \
                               /fastsurfer/run_fastsurfer.sh \
                              --fs_license /fs/license.txt \
                              --t1 /anat/"${idBIDS}"_t1w.nii.gz \
                              --sid "${idBIDS}" --sd /output --no_fs_T1 \
                              --parallel --threads "${threads}"
        chmod aug+wr -R ${SUBJECTS_DIR}/${idBIDS}
    else
        Info "Running Freesurfer 7.3.2 comform volume to minimum"

        # FIX FOV greater than 256
        t1nii="${t1_2proc}"
        dim=($(mrinfo ${t1nii} -size))
        res=($(mrinfo ${t1nii} -spacing))
        fov=$(printf "%.0f" $(bc -l <<< "scale=2; ${dim[2]}*${res[2]}"))

        if [ ${fov} -gt 256 ]; then
          Info "Cropping structural image to 256 for surface reconstruction compatibility"
          crop=$(bc -l <<< "scale=0; (${fov}-256)/${res[2]}")
          Do_cmd mrgrid ${t1nii} crop -axis 2 0,${crop} ${tmp}/_t1w_croped.nii.gz
          t1nii=${tmp}/_t1w_croped.nii.gz
        else
          crop="FALSE"
        fi

        # Run recon-all -autorecon1
        Do_cmd recon-all -autorecon1 -cm -parallel -openmp ${threads} -i "${t1nii}" -s "${idBIDS}"

        # Replace brainmask.mgz with mri_synthstrip mask
        Do_cmd mri_synthstrip -i ${SUBJECTS_DIR}/${idBIDS}/mri/T1.mgz -o ${SUBJECTS_DIR}/${idBIDS}/mri/brainmask.auto.mgz --no-csf
        Do_cmd cp ${SUBJECTS_DIR}/${idBIDS}/mri/brainmask.auto.mgz ${SUBJECTS_DIR}/${idBIDS}/mri/brainmask.mgz

        # Run recon-all -autorecon2 weird bug on recon2 is skipping -careg (will run each step manually)
        Do_cmd recon-all -gcareg -cm -parallel -openmp ${threads} -s "${idBIDS}"
        Do_cmd recon-all -canorm -cm -parallel -openmp ${threads} -s "${idBIDS}"
        Do_cmd recon-all -careg -cm -parallel -openmp ${threads} -s "${idBIDS}"
        Do_cmd recon-all -calabel -cm -parallel -openmp ${threads} -s "${idBIDS}"
        Do_cmd recon-all -normalization2 -cm -parallel -openmp ${threads} -s "${idBIDS}"
        Do_cmd recon-all -maskbfs -cm -parallel -openmp ${threads} -s "${idBIDS}"
        Do_cmd recon-all -segmentation -cm -parallel -openmp ${threads} -s "${idBIDS}"
        Do_cmd recon-all -fill -cm -parallel -openmp ${threads} -s "${idBIDS}"
        Do_cmd recon-all -tessellate -cm -parallel -openmp ${threads} -s "${idBIDS}"
        Do_cmd recon-all -smooth1 -cm -parallel -openmp ${threads} -s "${idBIDS}"
        Do_cmd recon-all -inflate1 -cm -parallel -openmp ${threads} -s "${idBIDS}"
        Do_cmd recon-all -qsphere -cm -parallel -openmp ${threads} -s "${idBIDS}"
        Do_cmd recon-all -fix -cm -parallel -openmp ${threads} -s "${idBIDS}"
        Do_cmd recon-all -autorecon-pial -cm -parallel -openmp ${threads} -s "${idBIDS}"
        Do_cmd recon-all -autorecon2-wm -cm -parallel -openmp ${threads} -s "${idBIDS}"
        # Do_cmd recon-all -white -cm -parallel -openmp ${threads} -s "${idBIDS}"
        # Do_cmd recon-all -smooth2 -cm -parallel -openmp ${threads} -s "${idBIDS}"
        # Do_cmd recon-all -inflate2 -cm -parallel -openmp ${threads} -s "${idBIDS}"
        # Do_cmd recon-all -curvHK -cm -parallel -openmp ${threads} -s "${idBIDS}"
        # Do_cmd recon-all -curvstats -cm -parallel -openmp ${threads} -s "${idBIDS}"
        # Run autorecon3
        Do_cmd recon-all -autorecon3 -cm -parallel -openmp ${threads} -s "${idBIDS}"
    fi

    # Copy the freesurfer log to our MICA-log Directory
    Do_cmd cp "${SUBJECTS_DIR}/${idBIDS}/scripts/recon-all.log" "${dir_logs}/recon-all.log"

    # Copy results from TMP to deviratives/SUBJECTS_DIR directory
    Do_cmd cp -r "${SUBJECTS_DIR}/${idBIDS}" "${dir_surf}"
fi
Note "Check log file:" "${dir_logs}/recon-all.log"

# -----------------------------------------------------------------------------------------------
# Check proc_surf status
if [[ -f "${dir_logs}/recon-all.log" ]] && grep -q "finished without error" "${dir_logs}/recon-all.log"; then ((Nsteps++)); fi

# Create json file for T1native
proc_surf_json="${proc_struct}/surf/${idBIDS}_proc_surf-${recon}.json"
json_surf "${t1_2proc}" "${dir_surf}" "${recon}" "${proc_surf_json}"

# Notification of completition
micapipe_completition_status proc_surf
micapipe_procStatus "${id}" "${SES/ses-/}" "proc_surf-${recon}" "${out}/micapipe_processed_sub.csv"
micapipe_procStatus_json "${id}" "${SES/ses-/}" "proc_surf-${recon}" "${module_json}"
cleanup "$tmp" "$nocleanup" "$here"
