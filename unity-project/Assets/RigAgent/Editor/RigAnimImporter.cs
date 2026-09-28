using System;
using System.Collections.Generic;
using System.IO;
using UnityEditor;
using UnityEditor.Animations;
using UnityEngine;
using UnityEngine.SceneManagement;
using UnityEngine.U2D.IK;

namespace RigAgent
{
    /// <summary>
    /// Imports an animation clip baked by rig-agent onto a rig that is already in the scene
    /// (Goal 2, A2), and checks it.
    ///
    /// Python writes Assets/Rigs/animation_request.json: the clip as flat tracks (JsonUtility cannot
    /// read the dictionaries of animation.json) plus which rig object it is for. This builds an
    /// AnimationClip with, for every frame:
    ///   - each animated bone's z rotation (and the hip's position),
    ///   - each IK target's position and rotation (IK/&lt;chain&gt;/target_&lt;effector&gt;),
    /// saves it as &lt;asset folder&gt;/&lt;clip&gt;.anim with an Animator Controller beside it,
    /// and gives the rig an Animator that plays it, so pressing Play shows the loop.
    ///
    /// The rotation curves and the IK target curves describe the same pose (Python bakes both from
    /// one solve). The report proves it: at a few frames it samples the clip, reads the bones, then
    /// lets Unity's own IK solvers re-solve from the sampled targets and reads them again. Python
    /// compares both readings with its own forward kinematics. The scene is restored afterwards.
    /// </summary>
    public static class RigAnimImporter
    {
        public const string AnimRequestFile = "animation_request.json";
        public const string AnimReportFile = "last_anim_import.json";
        public const string MenuImportAnimation = "Tools/Rig Agent/Import Latest Animation";

        const string RotationZ = "localEulerAnglesRaw.z";

        // ---- JSON shapes ---------------------------------------------------------------------

        [Serializable]
        public class RotationTrack
        {
            public string bone;
            public float[] values;
        }

        [Serializable]
        public class PositionTrack
        {
            public string bone;
            public float[] x;
            public float[] y;
        }

        [Serializable]
        public class TargetTrack
        {
            public string chain;
            public string target;
            public float[] x;
            public float[] y;
            public float[] rot;
        }

        [Serializable]
        public class AnimRequest
        {
            public string[] rig_names; // the rig object to animate: the first one found wins
            public string name;
            public string clip;
            public int fps;
            public int frame_count;
            public bool loop = true;
            public float ground_speed;
            public string asset_folder; // empty: Assets/Rigs/Generated/<rig>
            public RotationTrack[] rotations;
            public PositionTrack[] positions;
            public TargetTrack[] targets;
            public int[] check_frames;
        }

        [Serializable]
        public class PointReport
        {
            public string name;
            public float[] head;
        }

        [Serializable]
        public class FrameSample
        {
            public int frame;
            public List<PointReport> bones = new List<PointReport>(); // posed by the clip's rotation curves
            public List<PointReport> solved = new List<PointReport>(); // after Unity's IK re-solved from the targets
        }

        [Serializable]
        public class AnimReport
        {
            public bool ok;
            public string rig_object = "";
            public string clip_path = "";
            public string controller_path = "";
            public int frame_count;
            public float length_seconds;
            public bool loop;
            public int rotation_curves;
            public int position_curves;
            public int target_curves;
            public bool animator;
            public List<string> missing = new List<string>();
            public List<FrameSample> samples = new List<FrameSample>();
            public List<string> errors = new List<string>();
        }

        // ---- menu ----------------------------------------------------------------------------

        [MenuItem(MenuImportAnimation)]
        public static void ImportLatest()
        {
            var report = new AnimReport();
            try
            {
                string path = Path.Combine(RigImporter.RigsDir, AnimRequestFile);
                if (!File.Exists(path))
                    throw new FileNotFoundException("animation request not found: " + path);
                AnimRequest request = JsonUtility.FromJson<AnimRequest>(File.ReadAllText(path));
                Import(request, report);
            }
            catch (Exception e)
            {
                report.errors.Add(e.Message);
            }

            report.ok = report.errors.Count == 0 && report.missing.Count == 0;
            Directory.CreateDirectory(RigImporter.RigsDir);
            string reportPath = Path.Combine(RigImporter.RigsDir, AnimReportFile);
            File.WriteAllText(reportPath, JsonUtility.ToJson(report, true));
            AssetDatabase.ImportAsset(reportPath);

            if (report.ok)
                Debug.Log($"{RigImporter.LogTag} Animation '{report.clip_path}' on {report.rig_object}: {report.frame_count} frames, {report.rotation_curves} rotation, {report.target_curves} IK target curves");
            else
                Debug.LogError($"{RigImporter.LogTag} Animation import failed: {string.Join("; ", report.errors)}{(report.missing.Count > 0 ? " missing: " + string.Join(", ", report.missing) : "")}");
        }

        // ---- import --------------------------------------------------------------------------

        static void Import(AnimRequest request, AnimReport report)
        {
            if (request == null || request.fps <= 0 || request.frame_count < 2)
                throw new InvalidOperationException("the request has no usable fps or frame_count");
            GameObject rig = FindRig(request.rig_names);
            if (rig == null)
                throw new InvalidOperationException($"no rig named {string.Join(" or ", request.rig_names ?? new string[0])} under {RigImporter.OutputRoot}; import the skeleton first");
            report.rig_object = rig.name;
            report.frame_count = request.frame_count;
            report.loop = request.loop;

            var bones = new Dictionary<string, Transform>();
            foreach (BoneGizmo gizmo in rig.GetComponentsInChildren<BoneGizmo>(true))
                bones[gizmo.name] = gizmo.transform;

            var clip = new AnimationClip { frameRate = request.fps, name = request.name };
            foreach (RotationTrack track in request.rotations ?? new RotationTrack[0])
            {
                if (!bones.TryGetValue(track.bone, out Transform bone)) { report.missing.Add(track.bone); continue; }
                SetRotation(clip, PathOf(bone, rig.transform), track.values, request);
                report.rotation_curves++;
            }
            foreach (PositionTrack track in request.positions ?? new PositionTrack[0])
            {
                if (!bones.TryGetValue(track.bone, out Transform bone)) { report.missing.Add(track.bone); continue; }
                SetPosition(clip, PathOf(bone, rig.transform), track.x, track.y, bone.localPosition.z, request);
                report.position_curves++;
            }
            foreach (TargetTrack track in request.targets ?? new TargetTrack[0])
            {
                Transform target = rig.transform.Find(RigIk.IkRootName + "/" + track.chain + "/" + track.target);
                if (target == null) { report.missing.Add(track.target); continue; }
                string path = PathOf(target, rig.transform);
                SetPosition(clip, path, track.x, track.y, 0f, request);
                SetRotation(clip, path, track.rot, request);
                report.target_curves++;
            }

            var settings = AnimationUtility.GetAnimationClipSettings(clip);
            settings.loopTime = request.loop;
            AnimationUtility.SetAnimationClipSettings(clip, settings);
            report.length_seconds = clip.length;

            string folder = string.IsNullOrEmpty(request.asset_folder)
                ? RigImporter.GeneratedDir + "/" + RigSkin.SafeName(rig.name)
                : request.asset_folder;
            RigImporter.EnsureFolder(folder);
            report.clip_path = SaveClip(clip, folder + "/" + RigSkin.SafeName(request.name) + ".anim");
            var saved = AssetDatabase.LoadAssetAtPath<AnimationClip>(report.clip_path);
            report.controller_path = AttachAnimator(rig, saved, folder + "/" + RigSkin.SafeName(rig.name) + ".controller");
            report.animator = rig.GetComponent<Animator>() != null;

            Sample(rig, saved, bones, request, report);
            EditorSceneManagerMarkDirty(rig);
        }

        static GameObject FindRig(string[] names)
        {
            GameObject output = null;
            foreach (GameObject root in SceneManager.GetActiveScene().GetRootGameObjects())
                if (root.name == RigImporter.OutputRoot) { output = root; break; }
            if (output == null || names == null)
                return null;
            foreach (string name in names)
            {
                Transform rig = output.transform.Find(name);
                if (rig != null)
                    return rig.gameObject;
            }
            return null;
        }

        static string PathOf(Transform t, Transform root) => AnimationUtility.CalculateTransformPath(t, root);

        static AnimationCurve Curve(float[] values, AnimRequest request)
        {
            if (values == null || values.Length != request.frame_count)
                throw new InvalidOperationException($"a track has {(values == null ? 0 : values.Length)} values, expected {request.frame_count}");
            var keys = new Keyframe[values.Length];
            for (int i = 0; i < values.Length; i++)
                keys[i] = new Keyframe(i / (float)request.fps, values[i]);
            var curve = new AnimationCurve(keys);
            for (int i = 0; i < keys.Length; i++)
            {
                // linear between the baked frames: no overshoot the validator never saw
                AnimationUtility.SetKeyLeftTangentMode(curve, i, AnimationUtility.TangentMode.Linear);
                AnimationUtility.SetKeyRightTangentMode(curve, i, AnimationUtility.TangentMode.Linear);
            }
            return curve;
        }

        static AnimationCurve Constant(float value, AnimRequest request)
        {
            float end = (request.frame_count - 1) / (float)request.fps;
            return AnimationCurve.Linear(0f, value, end, value);
        }

        static void SetRotation(AnimationClip clip, string path, float[] z, AnimRequest request)
        {
            // Euler curves need all three axes; a 2D rig only turns about z
            AnimationUtility.SetEditorCurve(clip, EditorCurveBinding.FloatCurve(path, typeof(Transform), "localEulerAnglesRaw.x"), Constant(0f, request));
            AnimationUtility.SetEditorCurve(clip, EditorCurveBinding.FloatCurve(path, typeof(Transform), "localEulerAnglesRaw.y"), Constant(0f, request));
            AnimationUtility.SetEditorCurve(clip, EditorCurveBinding.FloatCurve(path, typeof(Transform), RotationZ), Curve(z, request));
        }

        static void SetPosition(AnimationClip clip, string path, float[] x, float[] y, float z, AnimRequest request)
        {
            AnimationUtility.SetEditorCurve(clip, EditorCurveBinding.FloatCurve(path, typeof(Transform), "m_LocalPosition.x"), Curve(x, request));
            AnimationUtility.SetEditorCurve(clip, EditorCurveBinding.FloatCurve(path, typeof(Transform), "m_LocalPosition.y"), Curve(y, request));
            AnimationUtility.SetEditorCurve(clip, EditorCurveBinding.FloatCurve(path, typeof(Transform), "m_LocalPosition.z"), Constant(z, request));
        }

        /// <summary>Saves the clip, updating an existing asset in place so references survive.</summary>
        static string SaveClip(AnimationClip clip, string path)
        {
            var existing = AssetDatabase.LoadAssetAtPath<AnimationClip>(path);
            if (existing == null)
                AssetDatabase.CreateAsset(clip, path);
            else
            {
                EditorUtility.CopySerialized(clip, existing);
                existing.name = Path.GetFileNameWithoutExtension(path);
                EditorUtility.SetDirty(existing);
            }
            AssetDatabase.SaveAssets();
            return path;
        }

        /// <summary>One controller per rig, one state per clip; the clip imported last plays by default.</summary>
        static string AttachAnimator(GameObject rig, AnimationClip clip, string path)
        {
            var controller = AssetDatabase.LoadAssetAtPath<AnimatorController>(path)
                ?? AnimatorController.CreateAnimatorControllerAtPath(path);
            AnimatorStateMachine machine = controller.layers[0].stateMachine;
            AnimatorState state = null;
            foreach (ChildAnimatorState child in machine.states)
                if (child.state.name == clip.name) { state = child.state; break; }
            if (state == null)
                state = machine.AddState(clip.name);
            state.motion = clip;
            machine.defaultState = state;
            EditorUtility.SetDirty(controller);
            AssetDatabase.SaveAssets();

            Animator animator = rig.GetComponent<Animator>();
            if (animator == null)
                animator = Undo.AddComponent<Animator>(rig);
            animator.runtimeAnimatorController = controller;
            animator.applyRootMotion = false; // in-place cycles: the game moves the character
            return path;
        }

        // ---- the check -----------------------------------------------------------------------

        /// <summary>Samples the clip at the requested frames: the bones as the curves pose them, then
        /// again after Unity's IK solvers re-solve from the sampled targets. Restores the scene.</summary>
        static void Sample(GameObject rig, AnimationClip clip, Dictionary<string, Transform> bones, AnimRequest request, AnimReport report)
        {
            var saved = new List<(Transform t, Vector3 p, Quaternion r)>();
            foreach (Transform t in rig.GetComponentsInChildren<Transform>(true))
                saved.Add((t, t.localPosition, t.localRotation));
            IKManager2D manager = rig.GetComponentInChildren<IKManager2D>(true);

            AnimationMode.StartAnimationMode();
            try
            {
                foreach (int frame in request.check_frames ?? new int[0])
                {
                    var sample = new FrameSample { frame = frame };
                    AnimationMode.BeginSampling();
                    AnimationMode.SampleAnimationClip(rig, clip, frame / (float)request.fps);
                    AnimationMode.EndSampling();
                    Read(rig, bones, sample.bones);
                    if (manager != null)
                    {
                        manager.UpdateManager();
                        Read(rig, bones, sample.solved);
                    }
                    report.samples.Add(sample);
                }
            }
            finally
            {
                AnimationMode.StopAnimationMode();
                foreach (var (t, p, r) in saved)
                    if (t != null) { t.localPosition = p; t.localRotation = r; }
            }
        }

        static void Read(GameObject rig, Dictionary<string, Transform> bones, List<PointReport> into)
        {
            foreach (KeyValuePair<string, Transform> pair in bones)
            {
                Vector3 head = rig.transform.InverseTransformPoint(pair.Value.position);
                into.Add(new PointReport { name = pair.Key, head = new[] { head.x, head.y } });
            }
        }

        static void EditorSceneManagerMarkDirty(GameObject rig)
        {
            UnityEditor.SceneManagement.EditorSceneManager.MarkSceneDirty(rig.scene);
        }
    }
}
