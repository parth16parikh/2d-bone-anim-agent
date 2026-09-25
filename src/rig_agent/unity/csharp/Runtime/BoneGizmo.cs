using UnityEngine;

namespace RigAgent
{
    /// <summary>
    /// One bone of an imported rig: its length and metadata, plus a gizmo that draws it, so the
    /// rig is visible in the Scene view before any sprite exists (LLD 3.11a).
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

        public static bool ShowGizmos = true;

        static readonly Color LeftColor = new Color(0.36f, 0.62f, 1f);
        static readonly Color RightColor = new Color(1f, 0.56f, 0.30f);
        static readonly Color CenterColor = new Color(0.32f, 0.81f, 0.40f);
        static readonly Color ExtraColor = new Color(0.80f, 0.36f, 0.91f);

        Color BoneColor()
        {
            Color color = isExtra ? ExtraColor
                : name.EndsWith("_L") ? LeftColor
                : name.EndsWith("_R") ? RightColor
                : CenterColor;
            // bones behind the torso plane are drawn dimmer
            color.a = depth < 0 ? 0.55f : 1f;
            return color;
        }

        void OnDrawGizmos()
        {
            if (!ShowGizmos || length <= 0f)
                return;

            float width = Mathf.Clamp(length * 0.18f, 0.012f, 0.09f);
            Vector3 head = transform.position;
            Vector3 shoulder = transform.TransformPoint(new Vector3(length * 0.18f, width, 0f));
            Vector3 tail = transform.TransformPoint(new Vector3(length, 0f, 0f));
            Vector3 other = transform.TransformPoint(new Vector3(length * 0.18f, -width, 0f));

            Gizmos.color = BoneColor();
            Gizmos.DrawLine(head, shoulder);
            Gizmos.DrawLine(shoulder, tail);
            Gizmos.DrawLine(tail, other);
            Gizmos.DrawLine(other, head);
            Gizmos.DrawSphere(head, isExtra ? 0.008f : 0.012f);
        }
    }
}
