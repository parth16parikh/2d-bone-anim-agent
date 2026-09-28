using System;
using System.IO;
using UnityEditor;
using UnityEngine;

namespace RigAgent
{
    /// <summary>
    /// Placeholder shapes (Goal 2, A2): a flat capsule on every bone, coloured by side (left blue,
    /// right orange, centre green, accessories purple) and sorted by depth, so an animated rig is
    /// watchable before it has any art. Each shape is a child object named "_shape" of its bone,
    /// so it moves rigidly with the bone and never affects the bone hierarchy itself.
    ///
    /// All shapes share one generated capsule sprite (white, drawn 9-sliced so its round ends stay
    /// round at any length), tinted per bone. It uses the unlit sprite material when URP provides
    /// one, so the shapes show up in a 2D scene without a 2D light.
    /// </summary>
    public static class RigShapes
    {
        public const string ShapeName = "_shape";
        const string CapsuleFolder = RigImporter.GeneratedDir + "/_shared";
        const string CapsulePath = CapsuleFolder + "/capsule.png";
        const int CapsuleWidth = 256, CapsuleHeight = 64, CapsulePpu = 256;
        const string UnlitMaterial = "Packages/com.unity.render-pipelines.universal/Runtime/Materials/Sprite-Unlit-Default.mat";

        static readonly Color Left = new Color(0.18f, 0.44f, 0.93f, 0.9f);
        static readonly Color Right = new Color(0.91f, 0.35f, 0.05f, 0.9f);
        static readonly Color Centre = new Color(0.17f, 0.54f, 0.24f, 0.9f);
        static readonly Color Extra = new Color(0.61f, 0.21f, 0.71f, 0.9f);

        /// <summary>Adds a shape to every bone except the root marker. Returns how many.</summary>
        public static int Attach(RigImporter.SkeletonData skeleton, Transform[] bones)
        {
            Sprite capsule = CapsuleSprite();
            var material = AssetDatabase.LoadAssetAtPath<Material>(UnlitMaterial);
            float H = skeleton.height;
            int count = 0;
            foreach (RigImporter.BoneData bone in skeleton.bones)
            {
                if (bone.parent_id < 0)
                    continue; // the root is a tiny placement marker, not a body part

                var shape = new GameObject(ShapeName);
                shape.transform.SetParent(bones[bone.id], false);
                var renderer = shape.AddComponent<SpriteRenderer>();
                renderer.sprite = capsule;
                renderer.drawMode = SpriteDrawMode.Sliced;
                renderer.size = new Vector2(bone.length, Width(bone, H));
                renderer.color = ColourFor(bone.name);
                float sortingHint = bone.depth + (bone.layer == "behind" ? -0.5f : bone.layer == "front" ? 0.5f : 0f);
                renderer.sortingOrder = Mathf.RoundToInt(sortingHint * 10f);
                if (material != null)
                    renderer.sharedMaterial = material;
                count++;
            }
            return count;
        }

        static float Width(RigImporter.BoneData bone, float H)
        {
            if (bone.name == "head")
                return Mathf.Max(bone.length * 0.8f, 0.05f * H); // an oval head
            if (bone.name == "hip" || bone.name.StartsWith("spine") || bone.name == "chest")
                return 0.12f * H; // the torso is wider than the limbs
            return Mathf.Clamp(bone.length * 0.3f, 0.025f * H, 0.08f * H);
        }

        static Color ColourFor(string name)
        {
            if (name.StartsWith("extra_")) return Extra;
            if (name.EndsWith("_L")) return Left;
            if (name.EndsWith("_R")) return Right;
            return Centre;
        }

        /// <summary>The shared capsule sprite, generated once: pivot at its left end, so a shape
        /// starts at its bone's head and runs along the bone.</summary>
        static Sprite CapsuleSprite()
        {
            var sprite = AssetDatabase.LoadAssetAtPath<Sprite>(CapsulePath);
            if (sprite != null)
                return sprite;

            RigImporter.EnsureFolder(CapsuleFolder);
            var texture = new Texture2D(CapsuleWidth, CapsuleHeight, TextureFormat.RGBA32, false);
            float r = CapsuleHeight / 2f - 1f, cy = CapsuleHeight / 2f;
            for (int y = 0; y < CapsuleHeight; y++)
                for (int x = 0; x < CapsuleWidth; x++)
                {
                    float px = x + 0.5f, py = y + 0.5f;
                    float nearest = Mathf.Clamp(px, cy, CapsuleWidth - cy); // closest point on the centre line
                    float d = Vector2.Distance(new Vector2(px, py), new Vector2(nearest, cy));
                    texture.SetPixel(x, y, new Color(1f, 1f, 1f, Mathf.Clamp01(r - d + 0.5f)));
                }
            File.WriteAllBytes(CapsulePath, texture.EncodeToPNG());
            UnityEngine.Object.DestroyImmediate(texture);
            AssetDatabase.ImportAsset(CapsulePath);

            var importer = (TextureImporter)AssetImporter.GetAtPath(CapsulePath);
            importer.textureType = TextureImporterType.Sprite;
            importer.spriteImportMode = SpriteImportMode.Single;
            importer.spritePixelsPerUnit = CapsulePpu;
            importer.alphaIsTransparency = true;
            importer.mipmapEnabled = false;
            var settings = new TextureImporterSettings();
            importer.ReadTextureSettings(settings);
            settings.spriteAlignment = (int)SpriteAlignment.Custom;
            settings.spritePivot = new Vector2(0f, 0.5f);
            settings.spriteBorder = new Vector4(CapsuleHeight / 2f, 0f, CapsuleHeight / 2f, 0f); // keep the round ends
            settings.spriteMeshType = SpriteMeshType.FullRect; // needed for sliced drawing
            importer.SetTextureSettings(settings);
            importer.SaveAndReimport();

            sprite = AssetDatabase.LoadAssetAtPath<Sprite>(CapsulePath);
            if (sprite == null)
                throw new InvalidOperationException("could not create the capsule sprite at " + CapsulePath);
            return sprite;
        }
    }
}
