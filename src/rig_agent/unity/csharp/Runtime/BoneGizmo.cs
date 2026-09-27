using UnityEngine;

namespace RigAgent
{
    /// <summary>
    /// The metadata of one bone of an imported rig (LLD 3.11a). It draws nothing: bones are shown
    /// by Unity's own 2D Animation package, through the SpriteSkin on the rig root. The class name
    /// is kept from when it drew its own gizmo, so existing scenes and prefabs still resolve it.
    /// A bone points along its local +X axis and starts at the transform's position.
    /// </summary>
    [DisallowMultipleComponent]
    public class BoneGizmo : MonoBehaviour
    {
        public int boneId;
        public float length = 0.1f;

        [Tooltip("Positive = toward the camera (in front), negative = away, 0 = the torso plane.")]
        public int depth;

        [Tooltip("Extra bones only: 'front' or 'behind' (empty for canonical bones).")]
        public string layer = "";

        [Tooltip("Draw-order hint: depth shifted by -0.5 for 'behind' and +0.5 for 'front'.")]
        public float sortingHint;

        [Tooltip("Name of the IK chain this bone belongs to (arm_L, arm_R, leg_L, leg_R), if any.")]
        public string ikChain = "";

        public string mirrorOf = "";
        public bool isExtra;
    }
}
