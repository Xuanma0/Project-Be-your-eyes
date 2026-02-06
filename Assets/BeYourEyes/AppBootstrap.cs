using BeYourEyes.Adapters;
using BeYourEyes.Presenters.Audio;
using BeYourEyes.Presenters.DebugHUD;
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
            var bootstrap = FindObjectOfType<AppBootstrap>();
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

            if (FindObjectOfType<DebugAudioPresenter>() == null)
            {
                host.AddComponent<DebugAudioPresenter>();
            }

            if (FindObjectOfType<MockEventSource>() == null)
            {
                host.AddComponent<MockEventSource>();
            }
        }
    }
}
