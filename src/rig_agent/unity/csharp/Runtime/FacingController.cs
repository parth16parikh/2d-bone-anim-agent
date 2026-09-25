using UnityEngine;

namespace RigAgent
{
    /// <summary>
    /// Side-view rigs are always built facing right (+X). This flips the rig root with
    /// scale.x = -1 to face left, so one rig serves both directions (LLD 2.1, 3.11a).
    /// </summary>
    [DisallowMultipleComponent]
    public class FacingController : MonoBehaviour
    {
        [SerializeField] bool facingRight = true;

        public bool FacingRight => facingRight;

        public void Face(bool right)
        {
            facingRight = right;
            Vector3 scale = transform.localScale;
            scale.x = Mathf.Abs(scale.x) * (right ? 1f : -1f);
            transform.localScale = scale;
        }

        public void Flip() => Face(!facingRight);

        [ContextMenu("Face Right")]
        void FaceRightMenu() => Face(true);

        [ContextMenu("Face Left")]
        void FaceLeftMenu() => Face(false);

        void OnValidate() => Face(facingRight);
    }
}
