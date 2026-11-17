// Copied into Assets/LuxoddBuild/Editor/ by the luxodd/game-build workflow; not part of any game.
// Builds the project for the web with the fixed settings the attestation vouches for, and
// writes those settings next to the build so they are covered by the build-file hashes.
using System;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEditor.Build.Reporting;
using UnityEngine;
using UnityEngine.Rendering;

namespace Luxodd.Build
{
    public static class LuxoddWebGLBuild
    {
        // Entry point for GameCI: buildMethod: Luxodd.Build.LuxoddWebGLBuild.Build
        public static void Build()
        {
            var outputPath = Arg("-customBuildPath") ?? "build/WebGL";
            var graphics = (Arg("-luxoddGraphics") ?? "webgl2").ToLowerInvariant();

            PlayerSettings.WebGL.template = "PROJECT:LuxoddTemplate";
            PlayerSettings.WebGL.compressionFormat = WebGLCompressionFormat.Gzip;
            // Luxodd serves build files without a Content-Encoding header (server /proxy and /web/static), so the
            // loader must decompress them itself; 18 of 21 game projects already have this on.
            PlayerSettings.WebGL.decompressionFallback = true;
            PlayerSettings.WebGL.threadsSupport = false;
            PlayerSettings.WebGL.dataCaching = true;
            PlayerSettings.SetUseDefaultGraphicsAPIs(BuildTarget.WebGL, false);
            PlayerSettings.SetGraphicsAPIs(BuildTarget.WebGL, GraphicsApis(graphics));
            EditorUserBuildSettings.development = false;

            var scenes = EditorBuildSettings.scenes.Where(s => s.enabled).Select(s => s.path).ToArray();
            if (scenes.Length == 0)
            {
                Fail("No enabled scenes in Build Settings.");
            }

            var report = BuildPipeline.BuildPlayer(new BuildPlayerOptions
            {
                scenes = scenes,
                locationPathName = outputPath,
                target = BuildTarget.WebGL,
                options = BuildOptions.None,
            });

            if (report.summary.result != BuildResult.Succeeded)
            {
                Fail($"Build {report.summary.result}: {report.summary.totalErrors} error(s).");
            }

            var settings = new BuildSettingsRecord
            {
                unityVersion = Application.unityVersion,
                graphics = graphics,
                template = PlayerSettings.WebGL.template,
                compression = PlayerSettings.WebGL.compressionFormat.ToString(),
                threads = PlayerSettings.WebGL.threadsSupport,
                development = EditorUserBuildSettings.development,
                scenes = scenes,
                totalSizeBytes = (long)report.summary.totalSize,
                buildSeconds = report.summary.totalTime.TotalSeconds,
            };
            File.WriteAllText(Path.Combine(outputPath, "luxodd-build-settings.json"),
                JsonUtility.ToJson(settings, true));
            Debug.Log($"[LuxoddWebGLBuild] OK {outputPath} {report.summary.totalSize} bytes");
        }

        private static GraphicsDeviceType[] GraphicsApis(string graphics)
        {
            switch (graphics)
            {
                case "webgl2":
                    return new[] { GraphicsDeviceType.OpenGLES3 };
#if UNITY_6000_0_OR_NEWER
                case "webgpu":
                    return new[] { GraphicsDeviceType.WebGPU };
#endif
                default:
                    Fail($"Unsupported graphics target '{graphics}' for Unity {Application.unityVersion}.");
                    return null;
            }
        }

        private static string Arg(string name)
        {
            var args = Environment.GetCommandLineArgs();
            var i = Array.IndexOf(args, name);
            return i >= 0 && i + 1 < args.Length ? args[i + 1] : null;
        }

        private static void Fail(string message)
        {
            Debug.LogError("[LuxoddWebGLBuild] " + message);
            EditorApplication.Exit(1);
            throw new Exception(message);
        }

        [Serializable]
        private class BuildSettingsRecord
        {
            public string unityVersion;
            public string graphics;
            public string template;
            public string compression;
            public bool threads;
            public bool development;
            public string[] scenes;
            public long totalSizeBytes;
            public double buildSeconds;
        }
    }
}
