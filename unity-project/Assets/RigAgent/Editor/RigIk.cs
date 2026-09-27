using System;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.U2D.IK;

namespace RigAgent
{
    /// <summary>
    /// Sets up Unity's 2D IK for the rig's arms and legs, from the ik_chains of skeleton.json
    /// (LLD 2.9, 3.11a). Each chain gets a Limb solver and a target object at its effector, so
    /// dragging the target (a hand or a foot) bends the limb and keeps it connected, instead of
    /// detaching the hand from the forearm. Everything lives under one "IK" object on the rig root:
    /// IK / &lt;chain&gt; (the solver) / target_&lt;effector&gt;.
    ///
    /// A chain is exactly the 3 bones LimbSolver2D takes (root, joint, effector: upper_arm/thigh,
    /// forearm/shin, hand/foot). Anything attached past the effector (an extra_ bone such as a
    /// held weapon, or a toe) is a rigid child of it: it turns with the hand or foot through
    /// ordinary parenting, not through its own IK, since a weapon or a toe has nothing to reach on
    /// its own. The targets start on the effectors, so the rest pose is unchanged. Chains without
    /// an effector (an arm without a hand) are skipped.
    ///
    /// RigIkTicker solves every manager under RigAgent_Output once per editor frame. IKManager2D
    /// is [ExecuteInEditMode] and its own LateUpdate() would normally do this, which is how
    /// dragging a target is meant to re-bend a limb live; in this project that LateUpdate never
    /// fires for a manager created from a menu item (confirmed live: moving a target's position
    /// and waiting several seconds never moved the effector), so without the ticker a target drag
    /// does nothing until something else happens to trigger a solve.
    /// </summary>
    public static class RigIk
    {
        public const string IkRootName = "IK";

        [Serializable]
        public class SolverReport
        {
            public string chain = "";
            public string effector = "";
            public string target = "";
            public bool flip;
            public bool valid;
        }

        [Serializable]
        public class IkReport
        {
            public bool enabled;
            public List<SolverReport> solvers = new List<SolverReport>();
        }

        public static IkReport Attach(GameObject rigRoot, RigImporter.SkeletonData skeleton, Transform[] boneTransforms, bool enabled)
        {
            var report = new IkReport { enabled = enabled };
            if (!enabled || skeleton.ik_chains == null || skeleton.ik_chains.Length == 0)
                return report;

            var bones = new Dictionary<string, Transform>();
            foreach (RigImporter.BoneData b in skeleton.bones)
                bones[b.name] = boneTransforms[b.id];

            IKManager2D manager = null;
            GameObject ikRoot = null;
            foreach (RigImporter.IkChainData chain in skeleton.ik_chains)
            {
                if (string.IsNullOrEmpty(chain.effector))
                    continue; // no hand: nothing to reach with

                foreach (string name in new[] { chain.root, chain.joint, chain.effector })
                    if (!bones.ContainsKey(name))
                        throw new InvalidOperationException($"IK chain '{chain.name}' names the bone '{name}', which is not in the rig");
                Transform effector = bones[chain.effector];

                if (ikRoot == null)
                {
                    ikRoot = new GameObject(IkRootName);
                    ikRoot.transform.SetParent(rigRoot.transform, false);
                    manager = ikRoot.AddComponent<IKManager2D>();
                }

                var solverObject = new GameObject(chain.name);
                solverObject.transform.SetParent(ikRoot.transform, false);
                var solver = solverObject.AddComponent<LimbSolver2D>();

                var target = new GameObject("target_" + chain.effector).transform;
                target.SetParent(solverObject.transform, false);
                // Rest pose: the target sits on the effector and turns the same way. The solver makes the
                // effector take its target's rotation (constrainRotation), so a foot stays flat as the
                // leg moves, and a target with no rotation of its own would snap the hand or foot.
                target.SetPositionAndRotation(effector.position, effector.rotation);

                IKChain2D ikChain = solver.GetChain(0);
                ikChain.effector = effector;
                ikChain.target = target;
                ikChain.transformCount = 3; // upper limb, lower limb and the effector
                // "right" = the joint sits on the clockwise side of the line from the root to the
                // target, which is what LimbSolver2D calls flip (LLD 2.9)
                solver.flip = chain.bend_side == "right";
                solver.constrainRotation = true;

                manager.AddSolver(solver);
                solver.Initialize();

                report.solvers.Add(new SolverReport
                {
                    chain = chain.name,
                    effector = chain.effector,
                    target = target.name,
                    flip = solver.flip,
                    valid = ikChain.isValid,
                });
            }

            if (manager != null)
            {
                manager.alwaysUpdate = true; // do not wait for the placeholder sprite to be "visible"
                manager.UpdateManager();
            }
            return report;
        }
    }
}
