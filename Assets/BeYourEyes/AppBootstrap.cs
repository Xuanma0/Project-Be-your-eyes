using System;
using BeYourEyes.Adapters;
using BeYourEyes.Presenters.Audio;
using UnityEngine;

namespace BeYourEyes
{
    [DefaultExecutionOrder(-1000)]
    public sealed class AppBootstrap : MonoBehaviour
    {
        private void Awake()
        {
            AppServices.Init();
        }

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
        private static void EnsureRuntimeLoop()
        {
            var bootstrap = FindFirstObjectByType<AppBootstrap>();
            GameObject host;

            if (bootstrap == null)
            {
                host = new GameObject("BeYourEyes.Runtime");
                DontDestroyOnLoad(host);
                host.AddComponent<AppBootstrap>();
            }
            else
            {
                host = bootstrap.gameObject;
            }

            if (FindFirstObjectByType<DebugAudioPresenter>() == null)
            {
                host.AddComponent<DebugAudioPresenter>();
            }

            var wsType = Type.GetType("BeYourEyes.Adapters.Networking.GatewayWsClient, BeYourEyes.Unity");
            if (wsType != null)
            {
                if (host.GetComponent(wsType) == null)
                {
                    host.AddComponent(wsType);
                }

                return;
            }

            var pollerType = Type.GetType("BeYourEyes.Adapters.Networking.GatewayPoller, BeYourEyes.Unity");
            if (pollerType != null && host.GetComponent(pollerType) == null)
            {
                host.AddComponent(pollerType);
            }
        }
    }
}
