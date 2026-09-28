using System;
using System.Collections.Generic;
using System.IO;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace RigAgent
{
    /// <summary>
    /// Builds the bone hierarchy described by a skeleton.json in the open scene
    /// (LLD 3.4 #7, 3.11a). Everything it creates lives under one root object, RigAgent_Output.
    ///
    /// Each rig also gets a transparent placeholder sprite and a SkeletonAsset holding its bones
    /// (RigSkin), so Unity's own 2D Animation package draws the bones through a SpriteSkin.
    /// They are written into the rig's asset folder: Assets/Rigs/Generated/<rig> by default, or
    /// the folder named in Assets/Rigs/import_options.json (or per rig in the batch list).
    ///
    /// Arms and legs get 2D IK (RigIk): a Limb solver and a target per chain of ik_chains, so a
    /// hand or foot can be dragged without detaching from its limb.
    ///
    /// After building, it reads the real Transforms back and writes Assets/Rigs/last_import.json,
    /// so the Python side can verify what Unity actually created against the JSON.
    ///
    /// "Import All Rigs" builds every skeleton listed in Assets/Rigs/batch.json side by side and
    /// writes last_batch.json. "Save Rigs As Prefabs" saves the named rigs of the scene as prefab
    /// assets in the folder given in Assets/Rigs/prefab_request.json and writes last_prefabs.json.
    /// </summary>
    public static class RigImporter
    {
        // These strings are shared with the Python side (rig_agent/unity/contract.py).
        public const string OutputRoot = "RigAgent_Output";
        public const string RigsDir = "Assets/Rigs";
        public const string SkeletonFile = "skeleton.json";
        public const string ReportFile = "last_import.json";
        public const string LogTag = "[RigAgent]";
        public const string MenuImportLatest = "Tools/Rig Agent/Import Latest Skeleton";
        public const string BatchDir = "Assets/Rigs/Batch";
        public const string BatchFile = "batch.json";
        public const string BatchReportFile = "last_batch.json";
        public const string MenuImportAll = "Tools/Rig Agent/Import All Rigs";
        public const string PrefabFile = "prefab_request.json";
        public const string PrefabReportFile = "last_prefabs.json";
        public const string MenuSavePrefabs = "Tools/Rig Agent/Save Rigs As Prefabs";
        public const string GeneratedDir = "Assets/Rigs/Generated";
        public const string OptionsFile = "import_options.json";

        const string MenuImportFile = "Tools/Rig Agent/Import Skeleton...";
        const string MenuClear = "Tools/Rig Agent/Clear Output";
        static readonly string[] SupportedSchemas = { "1.0", "1.1" }; // 1.1 added ik_chains
        const float PositionTolerance = 1e-3f;
        const float BatchGap = 0.4f; // space between rigs placed side by side

        // ---- JSON shapes (JsonUtility ignores fields we do not declare) ----------------------

        [Serializable]
        public class BoneData
        {
            public int id;
            public string name;
            public int parent_id;
            public float[] world_head;
            public float[] world_tail;
            public float[] local_position;
            public float local_rotation_deg;
            public float length;
            public int depth;
            public string layer;
            public string ik_chain;
            public string mirror_of;
        }

        [Serializable]
        public class IkChainData
        {
            public string name;
            public string root;
            public string joint;
            public string effector; // empty when the rig has no hands
            public string bend_side; // "left" or "right", looking from the root toward the target
        }

        [Serializable]
        public class SkeletonData
        {
            public string schema_version;
            public string rig_name;
            public string source_prompt;
            public float height;
            public string view;
            public string facing;
            public string rest_pose;
            public string style;
            public int pixels_per_unit;
            public BoneData[] bones;
            public IkChainData[] ik_chains; // schema 1.1; absent in 1.0
        }

        [Serializable]
        public class BoneReport
        {
            public int id;
            public string name;
            public string parent;
            public string path;
            public float[] world_head;
            public float[] world_tail;
            public int depth;
            public string layer;
        }

        [Serializable]
        public class ImportReport
        {
            public bool ok;
            public string file = "";
            public string rig_name = "";
            public string view = "";
            public int bone_count;
            public string root_path = "";
            public float max_head_error;
            public float max_tail_error;
            public RigSkin.SkinReport skin = new RigSkin.SkinReport();
            public RigIk.IkReport ik = new RigIk.IkReport();
            public int shapes; // placeholder capsules added (one per bone but the root)
            public List<string> errors = new List<string>();
            public List<BoneReport> bones = new List<BoneReport>();
        }

        [Serializable]
        public class ImportOptions
        {
            public string asset_folder; // where this rig's sprite and skeleton asset go
            public bool ik = true; // set up the arm and leg IK
        }

        [Serializable]
        public class BatchManifest
        {
            public string[] files;
            public string[] asset_folders; // one per file; empty = the default folder
            public bool ik = true;
        }

        [Serializable]
        public class BatchReport
        {
            public bool ok;
            public List<string> errors = new List<string>();
            public List<ImportReport> rigs = new List<ImportReport>();
        }

        [Serializable]
        public class PrefabRequest
        {
            public string folder;
            public bool overwrite;
            public string[] rigs;
        }

        [Serializable]
        public class PrefabResult
        {
            public string rig = "";
            public string path = "";
            public string status = ""; // created, updated, kept or failed
            public string message = "";
        }

        [Serializable]
        public class PrefabReport
        {
            public bool ok;
            public string folder = "";
            public List<string> errors = new List<string>();
            public List<PrefabResult> results = new List<PrefabResult>();
        }

        // ---- menu items -----------------------------------------------------------------------

        [MenuItem(MenuImportLatest)]
        public static void ImportLatest()
        {
            string assetFolder = null;
            bool ik = true;
            string optionsPath = Path.Combine(RigsDir, OptionsFile);
            if (File.Exists(optionsPath))
            {
                ImportOptions options = JsonUtility.FromJson<ImportOptions>(File.ReadAllText(optionsPath));
                assetFolder = options?.asset_folder;
                ik = options == null || options.ik;
            }
            ImportFromPath(Path.Combine(RigsDir, SkeletonFile), assetFolder, ik);
        }

        [MenuItem(MenuImportFile)]
        public static void ImportChosen()
        {
            string path = EditorUtility.OpenFilePanel("Import skeleton.json", "", "json");
            if (!string.IsNullOrEmpty(path))
                ImportFromPath(path);
        }

        [MenuItem(MenuImportAll)]
        public static void ImportAll()
        {
            var batch = new BatchReport();
            try
            {
                string manifestPath = Path.Combine(RigsDir, BatchFile);
                if (!File.Exists(manifestPath))
                    throw new FileNotFoundException("batch list not found: " + manifestPath);
                BatchManifest manifest = JsonUtility.FromJson<BatchManifest>(File.ReadAllText(manifestPath));
                if (manifest == null || manifest.files == null || manifest.files.Length == 0)
                    throw new InvalidOperationException("the batch list names no skeleton files");

                // Start from an empty RigAgent_Output so the row is laid out from scratch.
                ClearOutputChildren();

                float cursor = 0f;
                bool first = true;
                for (int index = 0; index < manifest.files.Length; index++)
                {
                    string file = manifest.files[index];
                    string assetFolder = manifest.asset_folders != null && index < manifest.asset_folders.Length ? manifest.asset_folders[index] : null;
                    var report = new ImportReport { file = file };
                    try
                    {
                        SkeletonData skeleton = ReadSkeleton(file);
                        float minX = float.MaxValue, maxX = float.MinValue;
                        foreach (BoneData b in skeleton.bones)
                        {
                            minX = Mathf.Min(minX, Mathf.Min(b.world_head[0], b.world_tail[0]));
                            maxX = Mathf.Max(maxX, Mathf.Max(b.world_head[0], b.world_tail[0]));
                        }
                        if (first)
                            cursor = minX; // the first rig stays where its JSON puts it
                        first = false;
                        Import(skeleton, new Vector2(cursor - minX, 0f), report, assetFolder, manifest.ik);
                        cursor += (maxX - minX) + BatchGap;
                    }
                    catch (Exception e)
                    {
                        report.errors.Add(e.Message);
                    }
                    report.ok = report.errors.Count == 0;
                    batch.rigs.Add(report);
                }
            }
            catch (Exception e)
            {
                batch.errors.Add(e.Message);
            }

            batch.ok = batch.errors.Count == 0 && batch.rigs.TrueForAll(r => r.ok);
            WriteJson(BatchReportFile, batch);

            int good = batch.rigs.FindAll(r => r.ok).Count;
            if (batch.ok)
                Debug.Log($"{LogTag} Imported {good} rigs side by side under {OutputRoot}.");
            else
                Debug.LogError($"{LogTag} Batch import: {good} of {batch.rigs.Count} rigs imported. "
                    + string.Join("; ", batch.errors)
                    + string.Join("; ", batch.rigs.FindAll(r => !r.ok).ConvertAll(r => r.file + ": " + string.Join(", ", r.errors))));
        }

        [MenuItem(MenuSavePrefabs)]
        public static void SavePrefabs()
        {
            var report = new PrefabReport();
            try
            {
                string requestPath = Path.Combine(RigsDir, PrefabFile);
                if (!File.Exists(requestPath))
                    throw new FileNotFoundException("prefab request not found: " + requestPath);
                PrefabRequest request = JsonUtility.FromJson<PrefabRequest>(File.ReadAllText(requestPath));
                if (request == null || request.rigs == null || request.rigs.Length == 0)
                    throw new InvalidOperationException("the prefab request names no rigs");
                report.folder = CheckAssetFolder(request.folder, "prefab folder");

                GameObject output = FindOutputRoot();
                foreach (string rig in request.rigs)
                    report.results.Add(SavePrefab(output, rig, report.folder, request.overwrite));
                AssetDatabase.SaveAssets();
            }
            catch (Exception e)
            {
                report.errors.Add(e.Message);
            }

            report.ok = report.errors.Count == 0 && report.results.TrueForAll(r => r.status != "failed");
            WriteJson(PrefabReportFile, report);

            if (report.ok)
                Debug.Log($"{LogTag} Saved {report.results.Count} prefab(s) in {report.folder}.");
            else
                Debug.LogError($"{LogTag} Prefabs: " + string.Join("; ", report.errors)
                    + string.Join("; ", report.results.FindAll(r => r.status == "failed").ConvertAll(r => r.rig + ": " + r.message)));
        }

        [MenuItem(MenuClear)]
        public static void ClearOutput()
        {
            if (ClearOutputChildren())
                Debug.Log($"{LogTag} Cleared {OutputRoot}.");
        }

        static bool ClearOutputChildren()
        {
            GameObject root = FindOutputRoot();
            if (root == null)
                return false;
            for (int i = root.transform.childCount - 1; i >= 0; i--)
                Undo.DestroyObjectImmediate(root.transform.GetChild(i).gameObject);
            return true;
        }

        // ---- import ---------------------------------------------------------------------------

        /// <summary>Imports a skeleton.json and writes the verification report. Never throws.</summary>
        public static ImportReport ImportFromPath(string path, string assetFolder = null, bool ik = true)
        {
            var report = new ImportReport { file = path };
            try
            {
                Import(ReadSkeleton(path), Vector2.zero, report, assetFolder, ik);
            }
            catch (Exception e)
            {
                report.errors.Add(e.Message);
            }

            report.ok = report.errors.Count == 0;
            WriteJson(ReportFile, report);

            if (report.ok)
                Debug.Log($"{LogTag} Imported '{report.rig_name}' ({report.view} view): {report.bone_count} bones under {report.root_path}, max position error {report.max_head_error:E2}");
            else
                Debug.LogError($"{LogTag} Import failed: {string.Join("; ", report.errors)}");
            return report;
        }

        static SkeletonData ReadSkeleton(string path)
        {
            if (!File.Exists(path))
                throw new FileNotFoundException("skeleton file not found: " + path);

            SkeletonData skeleton = JsonUtility.FromJson<SkeletonData>(File.ReadAllText(path));
            Validate(skeleton);
            return skeleton;
        }

        /// <summary>Builds one rig. origin moves the whole rig; the report stays in the rig's own space.</summary>
        static void Import(SkeletonData skeleton, Vector2 origin, ImportReport report, string assetFolder, bool ik)
        {
            report.rig_name = skeleton.rig_name;
            report.view = skeleton.view;
            assetFolder = string.IsNullOrEmpty(assetFolder)
                ? GeneratedDir + "/" + RigSkin.SafeName(skeleton.rig_name)
                : CheckAssetFolder(assetFolder, "asset folder");

            Undo.IncrementCurrentGroup();
            int undoGroup = Undo.GetCurrentGroup();
            Undo.SetCurrentGroupName("Import rig " + skeleton.rig_name);

            GameObject output = FindOutputRoot();
            if (output == null)
            {
                output = new GameObject(OutputRoot);
                Undo.RegisterCreatedObjectUndo(output, "Create " + OutputRoot);
            }

            // replace a previous import of the same rig; nothing outside this root is touched
            Transform previous = output.transform.Find(skeleton.rig_name);
            if (previous != null)
                Undo.DestroyObjectImmediate(previous.gameObject);

            var rigRoot = new GameObject(skeleton.rig_name);
            Undo.RegisterCreatedObjectUndo(rigRoot, "Import rig " + skeleton.rig_name);
            rigRoot.transform.SetParent(output.transform, false);
            rigRoot.transform.localPosition = new Vector3(origin.x, origin.y, 0f);
            if (skeleton.view == "side")
                rigRoot.AddComponent<FacingController>().Face(true); // built facing right

            var transforms = new Transform[skeleton.bones.Length];
            foreach (BoneData bone in skeleton.bones)
            {
                var go = new GameObject(bone.name);
                Transform parent = bone.parent_id < 0 ? rigRoot.transform : transforms[bone.parent_id];
                go.transform.SetParent(parent, false);
                go.transform.localPosition = new Vector3(bone.local_position[0], bone.local_position[1], 0f);
                go.transform.localRotation = Quaternion.Euler(0f, 0f, bone.local_rotation_deg);

                var gizmo = go.AddComponent<BoneGizmo>();
                gizmo.boneId = bone.id;
                gizmo.length = bone.length;
                gizmo.depth = bone.depth;
                gizmo.layer = bone.layer ?? "";
                gizmo.sortingHint = bone.depth + (bone.layer == "behind" ? -0.5f : bone.layer == "front" ? 0.5f : 0f);
                gizmo.ikChain = bone.ik_chain ?? "";
                gizmo.mirrorOf = bone.mirror_of ?? "";
                gizmo.isExtra = bone.name.StartsWith("extra_");
                transforms[bone.id] = go.transform;
            }

            try
            {
                report.skin = RigSkin.Attach(rigRoot, skeleton, transforms, assetFolder);
            }
            catch (Exception e)
            {
                report.errors.Add("sprite and skeleton assets: " + e.Message);
            }

            try
            {
                report.ik = RigIk.Attach(rigRoot, skeleton, transforms, ik);
            }
            catch (Exception e)
            {
                report.errors.Add("IK setup: " + e.Message);
            }

            try
            {
                report.shapes = RigShapes.Attach(skeleton, transforms);
            }
            catch (Exception e)
            {
                report.errors.Add("placeholder shapes: " + e.Message);
            }

            ReadBack(skeleton, transforms, output.transform, origin, report);

            Selection.activeGameObject = rigRoot;
            EditorSceneManager.MarkSceneDirty(rigRoot.scene);
            Undo.CollapseUndoOperations(undoGroup);
            SceneView.RepaintAll();
        }

        /// <summary>Reads the created Transforms back and compares them with the JSON.</summary>
        static void ReadBack(SkeletonData skeleton, Transform[] transforms, Transform outputRoot, Vector2 origin, ImportReport report)
        {
            report.bone_count = transforms.Length;
            report.root_path = OutputRoot + "/" + skeleton.rig_name;
            float maxHead = 0f, maxTail = 0f;

            foreach (BoneData bone in skeleton.bones)
            {
                Transform t = transforms[bone.id];
                Vector3 head = t.position - (Vector3)origin;
                Vector3 tail = t.TransformPoint(new Vector3(bone.length, 0f, 0f)) - (Vector3)origin;
                maxHead = Mathf.Max(maxHead, Vector2.Distance(head, new Vector2(bone.world_head[0], bone.world_head[1])));
                maxTail = Mathf.Max(maxTail, Vector2.Distance(tail, new Vector2(bone.world_tail[0], bone.world_tail[1])));

                string parentName = bone.parent_id < 0 ? "" : transforms[bone.parent_id].name;
                if (t.parent != null && bone.parent_id >= 0 && t.parent.name != parentName)
                    report.errors.Add($"bone '{bone.name}' hangs from '{t.parent.name}', expected '{parentName}'");

                report.bones.Add(new BoneReport
                {
                    id = bone.id,
                    name = bone.name,
                    parent = parentName,
                    path = PathFrom(t, outputRoot),
                    world_head = new[] { head.x, head.y },
                    world_tail = new[] { tail.x, tail.y },
                    depth = bone.depth,
                    layer = bone.layer ?? "",
                });
            }

            report.max_head_error = maxHead;
            report.max_tail_error = maxTail;
            if (maxHead > PositionTolerance || maxTail > PositionTolerance)
                report.errors.Add($"positions differ from the JSON by up to {Mathf.Max(maxHead, maxTail):E2} (limit {PositionTolerance})");
        }

        static void Validate(SkeletonData skeleton)
        {
            var errors = new List<string>();
            if (skeleton == null || skeleton.bones == null || skeleton.bones.Length == 0)
                throw new InvalidOperationException("the file has no bones (is it a skeleton.json?)");
            if (Array.IndexOf(SupportedSchemas, skeleton.schema_version) < 0)
                errors.Add($"unsupported schema_version '{skeleton.schema_version}' (expected {string.Join(" or ", SupportedSchemas)})");
            if (string.IsNullOrEmpty(skeleton.rig_name))
                errors.Add("rig_name is empty");

            var names = new HashSet<string>();
            int roots = 0;
            for (int i = 0; i < skeleton.bones.Length; i++)
            {
                BoneData b = skeleton.bones[i];
                if (b.id != i) errors.Add($"bone {i} has id {b.id}; ids must be 0..n-1 in order");
                if (string.IsNullOrEmpty(b.name) || !names.Add(b.name)) errors.Add($"bone {i} has an empty or duplicate name '{b.name}'");
                if (b.parent_id == -1) roots++;
                else if (b.parent_id < 0 || b.parent_id >= i) errors.Add($"bone '{b.name}' has parent_id {b.parent_id}; a parent must come before its child");
                if (b.world_head == null || b.world_head.Length != 2 || b.world_tail == null || b.world_tail.Length != 2 || b.local_position == null || b.local_position.Length != 2)
                    errors.Add($"bone '{b.name}' needs world_head, world_tail and local_position as [x, y]");
            }
            if (roots != 1) errors.Add($"expected exactly one root bone, found {roots}");
            if (errors.Count > 0)
                throw new InvalidOperationException(string.Join("; ", errors));
        }

        // ---- helpers --------------------------------------------------------------------------

        static GameObject FindOutputRoot()
        {
            Scene scene = SceneManager.GetActiveScene();
            foreach (GameObject root in scene.GetRootGameObjects())
                if (root.name == OutputRoot)
                    return root;
            return null;
        }

        static string PathFrom(Transform t, Transform outputRoot)
        {
            string path = t.name;
            for (Transform p = t.parent; p != null && p != outputRoot.parent; p = p.parent)
                path = p.name + "/" + path;
            return path;
        }

        static void WriteJson(string fileName, object report)
        {
            Directory.CreateDirectory(RigsDir);
            string path = Path.Combine(RigsDir, fileName);
            File.WriteAllText(path, JsonUtility.ToJson(report, true));
            AssetDatabase.ImportAsset(path);
        }

        // ---- prefabs --------------------------------------------------------------------------

        /// <summary>The folder must be inside Assets; anything else is refused.</summary>
        static string CheckAssetFolder(string folder, string what)
        {
            string cleaned = (folder ?? "").Trim().Replace('\\', '/').Trim('/');
            string[] parts = cleaned.Split('/');
            if (parts[0] != "Assets")
                throw new InvalidOperationException($"the {what} must be inside Assets, got '{folder}'");
            foreach (string part in parts)
                if (part.Length == 0 || part.StartsWith(".") || part.IndexOfAny(Path.GetInvalidFileNameChars()) >= 0)
                    throw new InvalidOperationException($"'{folder}' is not a usable {what} (bad part '{part}')");
            return cleaned;
        }

        internal static void EnsureFolder(string folder)
        {
            string[] parts = folder.Split('/');
            string current = parts[0];
            for (int i = 1; i < parts.Length; i++)
            {
                string next = current + "/" + parts[i];
                if (!AssetDatabase.IsValidFolder(next))
                    AssetDatabase.CreateFolder(current, parts[i]);
                current = next;
            }
        }

        static PrefabResult SavePrefab(GameObject output, string rigName, string folder, bool overwrite)
        {
            var result = new PrefabResult { rig = rigName };
            try
            {
                Transform rig = output == null ? null : output.transform.Find(rigName);
                if (rig == null)
                    throw new InvalidOperationException($"'{rigName}' is not under {OutputRoot} in the open scene");

                // one folder per rig, next to its placeholder sprite and skeleton asset
                string rigFolder = folder + "/" + RigSkin.SafeName(rigName);
                EnsureFolder(rigFolder);
                result.path = rigFolder + "/" + RigSkin.SafeName(rigName) + ".prefab";
                bool exists = AssetDatabase.LoadAssetAtPath<GameObject>(result.path) != null;
                if (exists && !overwrite)
                {
                    result.status = "kept"; // it may have been edited since; leave it alone
                    return result;
                }

                // The prefab's root sits at the origin, wherever the rig stands in the scene.
                Vector3 position = rig.localPosition;
                rig.localPosition = Vector3.zero;
                try
                {
                    PrefabUtility.SaveAsPrefabAssetAndConnect(rig.gameObject, result.path, InteractionMode.AutomatedAction, out bool saved);
                    if (!saved)
                        throw new InvalidOperationException("Unity could not save " + result.path);
                }
                finally
                {
                    rig.localPosition = position;
                }
                result.status = exists ? "updated" : "created";
            }
            catch (Exception e)
            {
                result.status = "failed";
                result.message = e.Message;
            }
            return result;
        }
    }
}
