using BeYourEyes.Adapters;
using BeYourEyes.Core.EventBus;
using BeYourEyes.Core.Scheduling;
using UnityEngine;

namespace BeYourEyes.Presenters.Audio
{
    public sealed class DebugAudioPresenter : MonoBehaviour
    {
        private IEventBus bus;

        private void OnEnable()
        {
            AppServices.Init();
            bus = AppServices.Bus;
            bus.Subscribe<PromptEvent>(OnPromptEvent);
        }

        private void OnDisable()
        {
            if (bus == null)
            {
                return;
            }

            bus.Unsubscribe<PromptEvent>(OnPromptEvent);
            bus = null;
        }

        private static void OnPromptEvent(PromptEvent p)
        {
            if (p == null)
            {
                return;
            }

            Debug.Log($"[TTS] ({p.category}/{p.priority}) {p.text}");
        }
    }
}
