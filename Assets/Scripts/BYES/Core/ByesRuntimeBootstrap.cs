using BYES.Plan;
using BYES.Telemetry;
using BYES.UI;
using BeYourEyes.Adapters.Networking;
using UnityEngine;

namespace BYES.Core
{
    public sealed class ByesRuntimeBootstrap : MonoBehaviour
    {
        private static bool _bootstrapped;

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
        private static void Bootstrap()
        {
            if (_bootstrapped)
            {
                return;
            }

            var existing = FindFirstObjectByType<ByesRuntimeBootstrap>();
            if (existing != null)
            {
                _bootstrapped = true;
                existing.InitializeReferences();
                return;
            }

            var root = new GameObject("BYES_RuntimeBootstrap");
            DontDestroyOnLoad(root);
            root.AddComponent<ByesRuntimeBootstrap>();
            _bootstrapped = true;
        }

        private void Awake()
        {
            DontDestroyOnLoad(gameObject);
            InitializeReferences();
        }

        private void InitializeReferences()
        {
            var state = ByesSystemState.EnsureExists();
            _ = state;

            // Triggers telemetry singleton creation.
            _ = ByesFrameTelemetry.DeviceId;
            _ = ByesHaptics.Instance;
            _ = ByesModeManager.EnsureExists();
            _ = ByesOverlayAckThrottler.EnsureExists();
            _ = ByesOverlayRenderer.EnsureExists();
            _ = ByesConfirmPanel.EnsureExists();
            GatewayRuntimeContext.DeviceIdProvider = () => ByesFrameTelemetry.DeviceId;
            GatewayRuntimeContext.ApiModeProvider = () => ByesModeManager.ToApiMode(ByesModeManager.Instance.GetMode());
            GatewayRuntimeContext.FrameSentToTelemetrySink = (runId, frameSeq, captureTsMs) =>
            {
                ByesFrameTelemetry.OnFrameSentToGateway(runId, frameSeq, captureTsMs);
            };

            var gatewayClient = FindFirstObjectByType<GatewayClient>();
            var planClient = FindFirstObjectByType<PlanClient>();
            var legacyExecutor = FindFirstObjectByType<PlanExecutor>();
            var actionExecutor = FindFirstObjectByType<ActionPlanExecutor>();
            var modeHotkeys = FindFirstObjectByType<ByesModeHotkeys>();
            if (modeHotkeys == null)
            {
                gameObject.AddComponent<ByesModeHotkeys>();
            }

            if (planClient != null)
            {
                if (planClient.Executor == null && legacyExecutor != null)
                {
                    planClient.Executor = legacyExecutor;
                }
                if (planClient.ActionExecutor == null && actionExecutor != null)
                {
                    planClient.ActionExecutor = actionExecutor;
                }
                if (gatewayClient != null && !string.IsNullOrWhiteSpace(gatewayClient.BaseUrl))
                {
                    planClient.GatewayBaseUrl = gatewayClient.BaseUrl;
                }
            }
        }
    }
}
