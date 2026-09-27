using System;
using System.Collections.Generic;
using System.IO;
using System.Text.RegularExpressions;
using UnityEditor;
using UnityEditor.U2D.Sprites;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.U2D;
using UnityEngine.U2D.Animation;

namespace RigAgent
{
    /// <summary>
    /// Gives an imported rig Unity's own bone display (LLD 3.11a). The 2D Animation package draws
    /// bones only for a SpriteSkin whose sprite carries the bones, so each rig gets a fully
    /// transparent placeholder sprite that holds them, and a SkeletonAsset with the same bones
    /// (the file the importers' "Main Skeleton" field takes). Both are written into the rig's
    /// asset folder and rewritten on every import, so the folder is generated content.
    /// </summary>
    public static class RigSkin
    {
        const int Padding = 16; // pixels around the bones in the placeholder texture
        const int QuadHalf = 8; // half the size, in pixels, of the tiny mesh the sprite needs

        [Serializable]
        public class SkinReport
        {
            public string sprite_path = "";
            public string skeleton_path = "";
            public int sprite_bones;
            public int bind_poses;
            public bool has_weights;
            public string state = "";
        }

        /// <summary>A name that is safe in a file name (same rule as rig_agent/unity/batch.py).</summary>
        public static string SafeName(string name)
        {
            string safe = Regex.Replace(name ?? "", "[^A-Za-z0-9_.-]+", "_").Trim('.', '_');
            return safe.Length == 0 ? "rig" : safe;
        }

        public static string PlaceholderPath(string folder, string rigName) => folder + "/" + SafeName(rigName) + "_placeholder.png";
        public static string SkeletonPath(string folder, string rigName) => folder + "/" + SafeName(rigName) + "_skeleton.asset";

        /// <summary>Writes the sprite and skeleton assets and puts a SpriteSkin on the rig root.</summary>
        public static SkinReport Attach(GameObject rigRoot, RigImporter.SkeletonData skeleton, Transform[] boneTransforms, string assetFolder)
        {
            var report = new SkinReport();
            float ppu = skeleton.pixels_per_unit > 0 ? skeleton.pixels_per_unit : 100f;
            RigImporter.EnsureFolder(assetFolder);

            float minX = float.MaxValue, maxX = float.MinValue, minY = float.MaxValue, maxY = float.MinValue;
            foreach (RigImporter.BoneData b in skeleton.bones)
                foreach (float[] p in new[] { b.world_head, b.world_tail })
                {
                    minX = Mathf.Min(minX, p[0]); maxX = Mathf.Max(maxX, p[0]);
                    minY = Mathf.Min(minY, p[1]); maxY = Mathf.Max(maxY, p[1]);
                }
            int width = Mathf.Max(32, Mathf.CeilToInt((maxX - minX) * ppu) + 2 * Padding);
            int height = Mathf.Max(32, Mathf.CeilToInt((maxY - minY) * ppu) + 2 * Padding);
            // the rig's origin (world 0,0) sits at this pixel of the sprite, which is also its pivot
            var originPx = new Vector2(-minX * ppu + Padding, -minY * ppu + Padding);

            SpriteBone[] bones = SpriteBones(skeleton, ppu, originPx);

            report.sprite_path = PlaceholderPath(assetFolder, skeleton.rig_name);
            Sprite sprite = WritePlaceholderSprite(report.sprite_path, width, height, ppu, originPx, bones);

            report.skeleton_path = SkeletonPath(assetFolder, skeleton.rig_name);
            WriteSkeletonAsset(report.skeleton_path, bones);

            report.sprite_bones = sprite.GetBones().Length;
            report.bind_poses = sprite.GetBindPoses().Length;
            report.has_weights = sprite.HasVertexAttribute(VertexAttribute.BlendWeight);

            rigRoot.AddComponent<SpriteRenderer>().sprite = sprite;
            var skin = rigRoot.AddComponent<SpriteSkin>();
            skin.SetBoneTransforms(boneTransforms);
            report.state = skin.SetRootBone(boneTransforms[0]).ToString(); // "Ready" when Unity accepts the setup
            return report;
        }

        /// <summary>The bones in SpriteBone form: pixels, parent-relative, the root in sprite pixels.</summary>
        static SpriteBone[] SpriteBones(RigImporter.SkeletonData skeleton, float ppu, Vector2 originPx)
        {
            var bones = new SpriteBone[skeleton.bones.Length];
            foreach (RigImporter.BoneData b in skeleton.bones)
            {
                Vector2 position = new Vector2(b.local_position[0], b.local_position[1]) * ppu;
                if (b.parent_id < 0)
                    position += originPx;
                bones[b.id] = new SpriteBone
                {
                    name = b.name,
                    guid = Hash128.Compute(SafeName(skeleton.rig_name) + "/" + b.name).ToString(), // stable across imports
                    position = new Vector3(position.x, position.y, 0f),
                    rotation = Quaternion.Euler(0f, 0f, b.local_rotation_deg),
                    length = b.length * ppu,
                    parentId = b.parent_id,
                    color = Color.white,
                };
            }
            return bones;
        }

        static Sprite WritePlaceholderSprite(string path, int width, int height, float ppu, Vector2 originPx, SpriteBone[] bones)
        {
            var texture = new Texture2D(width, height, TextureFormat.RGBA32, false);
            texture.SetPixels32(new Color32[width * height]); // all zero: fully transparent
            File.WriteAllBytes(path, texture.EncodeToPNG());
            UnityEngine.Object.DestroyImmediate(texture);
            AssetDatabase.ImportAsset(path, ImportAssetOptions.ForceUpdate);

            var importer = (TextureImporter)AssetImporter.GetAtPath(path);
            importer.textureType = TextureImporterType.Sprite;
            importer.spriteImportMode = SpriteImportMode.Single;
            importer.spritePixelsPerUnit = ppu;
            importer.mipmapEnabled = false;
            importer.alphaIsTransparency = true;
            importer.textureCompression = TextureImporterCompression.Uncompressed;
            var settings = new TextureImporterSettings();
            importer.ReadTextureSettings(settings);
            settings.spriteAlignment = (int)SpriteAlignment.Custom;
            settings.spritePivot = new Vector2(originPx.x / width, originPx.y / height);
            importer.SetTextureSettings(settings);
            importer.SaveAndReimport();

            var factory = new SpriteDataProviderFactories();
            factory.Init();
            ISpriteEditorDataProvider provider = factory.GetSpriteEditorDataProviderFromObject(importer);
            provider.InitSpriteEditorDataProvider();
            GUID id = provider.GetSpriteRects()[0].spriteID;

            provider.GetDataProvider<ISpriteBoneDataProvider>().SetBones(id, new List<SpriteBone>(bones));

            // Skinning needs a mesh whose vertices are weighted to bones: one tiny quad on the root.
            var c = new Vector2(bones[0].position.x, bones[0].position.y); // the root bone, in sprite pixels
            var weight = new BoneWeight { boneIndex0 = 0, weight0 = 1f };
            var mesh = provider.GetDataProvider<ISpriteMeshDataProvider>();
            mesh.SetVertices(id, new[]
            {
                new Vertex2DMetaData { position = c + new Vector2(-QuadHalf, -QuadHalf), boneWeight = weight },
                new Vertex2DMetaData { position = c + new Vector2(QuadHalf, -QuadHalf), boneWeight = weight },
                new Vertex2DMetaData { position = c + new Vector2(-QuadHalf, QuadHalf), boneWeight = weight },
                new Vertex2DMetaData { position = c + new Vector2(QuadHalf, QuadHalf), boneWeight = weight },
            });
            mesh.SetIndices(id, new[] { 0, 1, 2, 2, 1, 3 });
            mesh.SetEdges(id, new[] { new Vector2Int(0, 1), new Vector2Int(1, 3), new Vector2Int(3, 2), new Vector2Int(2, 0) });

            provider.Apply();
            importer.SaveAndReimport();

            var sprite = AssetDatabase.LoadAssetAtPath<Sprite>(path);
            if (sprite == null)
                throw new InvalidOperationException("Unity did not produce a sprite at " + path);
            return sprite;
        }

        /// <summary>Creates the SkeletonAsset, or updates it in place so references to it survive.</summary>
        static void WriteSkeletonAsset(string path, SpriteBone[] bones)
        {
            var asset = AssetDatabase.LoadAssetAtPath<SkeletonAsset>(path);
            if (asset == null)
            {
                asset = ScriptableObject.CreateInstance<SkeletonAsset>();
                asset.SetSpriteBones(bones);
                AssetDatabase.CreateAsset(asset, path);
            }
            else
            {
                asset.SetSpriteBones(bones);
                EditorUtility.SetDirty(asset);
            }
            AssetDatabase.SaveAssets();
        }
    }
}
