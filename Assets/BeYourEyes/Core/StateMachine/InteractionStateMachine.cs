using System;

namespace BeYourEyes.Core.StateMachine
{
    public sealed class InteractionStateMachine
    {
        public InteractionState Current { get; private set; } = InteractionState.Idle;

        public event Action<InteractionState> OnStateChanged;

        public void SetState(InteractionState next)
        {
            if (Current == next)
            {
                return;
            }

            Current = next;
            OnStateChanged?.Invoke(Current);
        }
    }
}
