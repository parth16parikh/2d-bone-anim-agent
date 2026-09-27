using UnityEditor;
using UnityEngine;
using UnityEngine.SceneManagement;
using UnityEngine.U2D.IK;

namespace RigAgent
{
    /// <summary>
    /// Solves every IK manager under RigAgent_Output once per editor frame (LLD 3.11a).
    ///
    /// IKManager2D is [ExecuteInEditMode] and its own LateUpdate() calls UpdateManager() every
    /// frame, which is how the package expects dragging its target to re-bend a limb live in the
    /// Scene view. In this project that LateUpdate never fires for a manager RigIk creates from a
    /// menu item (confirmed live: moving a target's position directly and waiting several seconds
    /// never moved the effector), so a target drag did nothing until something else happened to
    /// trigger a solve. This ticks every manager explicitly instead, independent of why LateUpdate
    /// itself does not fire here.
    ///
    /// Re-scanning the scene each tick (rather than keeping our own list of managers) is
    /// deliberate: a plain list would go stale across a script recompile, since the components
    /// persist in the open scene but a static field does not survive the domain reload. The scan
    /// is cheap (skipped whenever there is no RigAgent_Output, and otherwise only as many managers
    /// as there are imported rigs).
    /// </summary>
    [InitializeOnLoad]
    static class RigIkTicker
    {
        static RigIkTicker()
        {
            EditorApplication.update += Tick;
        }

        static void Tick()
        {
            if (EditorApplication.isPlayingOrWillChangePlaymode)
                return; // Play mode already ticks IKManager2D itself

            Scene scene = SceneManager.GetActiveScene();
            GameObject output = null;
            foreach (GameObject root in scene.GetRootGameObjects())
                if (root.name == RigImporter.OutputRoot)
                {
                    output = root;
                    break;
                }
            if (output == null)
                return;

            foreach (IKManager2D manager in output.GetComponentsInChildren<IKManager2D>(false))
                if (manager.isActiveAndEnabled)
                    manager.UpdateManager();
        }
    }
}
