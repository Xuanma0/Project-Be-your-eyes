using System;
using System.Collections;
using BeYourEyes.Adapters;
using BeYourEyes.Core.Events;
using UnityEngine;

namespace BeYourEyes.Presenters.DebugHUD
{
    public sealed class MockEventSource : MonoBehaviour
    {
        private readonly WaitForSeconds tick = new WaitForSeconds(1f);
        private bool publishRisk = true;

        private IEnumerator Start()
        {
            AppServices.Init();

            while (true)
            {
                yield return tick;

                var nowMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
                var envelope = new EventEnvelope(
                    nowMs,
                    CoordFrame.World,
                    0.9f,
                    3000,
                    "mock");

                if (publishRisk)
                {
                    AppServices.Bus.Publish(new RiskEvent(envelope, "前方有障碍", 1.5f, 0f));
                }
                else
                {
                    AppServices.Bus.Publish(new PerceptionEvent(envelope, "检测到门"));
                }

                publishRisk = !publishRisk;
            }
        }
    }
}
