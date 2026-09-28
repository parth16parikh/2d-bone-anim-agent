"""Names shared by the Python side and the C# scripts (LLD 3.11). tests/test_unity_contract.py
checks that the C# sources use exactly these strings, so the two sides cannot drift apart."""

OUTPUT_ROOT = "RigAgent_Output"  # the only scene object the agent may create or replace
SCRIPTS_DIR = "Assets/RigAgent"  # where the C# scripts are installed
RIGS_DIR = "Assets/Rigs"  # where skeleton.json and the import report are exchanged
SKELETON_FILE = "skeleton.json"  # written by Python, read by the importer
REPORT_FILE = "last_import.json"  # written by the importer, read by Python
IMPORT_MENU = "Tools/Rig Agent/Import Latest Skeleton"  # imports RIGS_DIR/SKELETON_FILE
IMPORT_LOG_TAG = "[RigAgent]"  # every importer console line starts with this

# Importing every rig in out/ (batch): Python writes one skeleton file per rig into BATCH_DIR and a
# manifest listing them; the importer builds them side by side and writes one report for all.
BATCH_DIR = "Assets/Rigs/Batch"
BATCH_FILE = "batch.json"  # written by Python: {"files": ["Assets/Rigs/Batch/knight.json", ...]}
BATCH_REPORT_FILE = "last_batch.json"  # written by the importer: {"ok", "rigs": [<import report>]}
IMPORT_ALL_MENU = "Tools/Rig Agent/Import All Rigs"  # imports the rigs listed in BATCH_FILE

# Saving rigs as prefabs: Python writes the request, the importer saves prefab assets and reports.
PREFAB_FILE = "prefab_request.json"  # {"folder": "Assets/...", "overwrite": false, "rigs": [...]}
PREFAB_REPORT_FILE = "last_prefabs.json"  # {"ok", "results": [{"rig", "path", "status", ...}]}
SAVE_PREFABS_MENU = "Tools/Rig Agent/Save Rigs As Prefabs"

# Each imported rig gets a transparent placeholder sprite and a skeleton asset (so Unity's own bone
# display works). They go into the rig's asset folder: GENERATED_DIR/<rig> by default, or
# <prefab folder>/<rig> when prefabs are requested, so the prefab sits beside them.
GENERATED_DIR = "Assets/Rigs/Generated"
IMPORT_OPTIONS_FILE = "import_options.json"  # {"asset_folder": "...", "ik": true}, single import

# Animation clips (Goal 2, A2): Python writes the clip as flat tracks plus which rig object it is
# for; the importer builds an AnimationClip, an Animator Controller and an Animator on that rig, and
# reports samples of the posed rig (by the curves, and after Unity's IK re-solved from the targets).
ANIMATION_REQUEST_FILE = "animation_request.json"
ANIMATION_REPORT_FILE = "last_anim_import.json"
IMPORT_ANIMATION_MENU = "Tools/Rig Agent/Import Latest Animation"
