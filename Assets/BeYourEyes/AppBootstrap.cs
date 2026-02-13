using System;
using System.Collections;
using BeYourEyes.Adapters;
using BeYourEyes.Core.Events;
using BeYourEyes.Presenters.Audio;
using UnityEngine;

namespace BeYourEyes
{
    [DefaultExecutionOrder(-1000)]
    public sealed class AppBootstrap : MonoBehaviour
    {
        private readonly WaitForSeconds heartbeatTick = new WaitForSeconds(1f);
        private Coroutine heartbeatRoutine;

        private void Awake()
        {
            AppServices.Init();
        }

        private void OnEnable()
        {
            if (heartbeatRoutine == null)
            {
                heartbeatRoutine = StartCoroutine(HeartbeatLoop());
            }
        }

        private void OnDisable()
        {
            if (heartbeatRoutine != null)
            {
                StopCoroutine(heartbeatRoutine);
                heartbeatRoutine = null;
            }
        }

        private IEnumerator HeartbeatLoop()
        {
            while (true)
            {
                yield return heartbeatTick;

                var nowMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
                var envelope = new EventEnvelope(nowMs, CoordFrame.World, 1f, 2000, "app");
                AppServices.Bus.Publish(new SystemHealthEvent(envelope, "tick", -1));
            }
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

            var hudType = Type.GetType("BeYourEyes.Presenters.DebugHUD.DebugHudPresenter, BeYourEyes.Unity");
            if (hudType != null && host.GetComponent(hudType) == null)
            {
                host.AddComponent(hudType);
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
