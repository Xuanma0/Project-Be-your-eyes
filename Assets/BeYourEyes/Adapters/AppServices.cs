using System;
using BeYourEyes.Core.EventBus;
using BeYourEyes.Core.Scheduling;
using BeYourEyes.Core.StateMachine;

namespace BeYourEyes.Adapters
{
    public static class AppServices
    {
        private static bool initialized;
        private static PromptScheduler promptScheduler;

        public static IEventBus Bus { get; private set; }
        public static InteractionStateMachine StateMachine { get; private set; }

        public static void Init()
        {
            if (initialized)
            {
                return;
            }

            Bus = new EventBus();
            StateMachine = new InteractionStateMachine();
            promptScheduler = new PromptScheduler(Bus, UtcNowMs);
            initialized = true;
        }

        private static long UtcNowMs()
        {
            return DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
        }
    }
}
