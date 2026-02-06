using System;
using System.Collections.Generic;

namespace BeYourEyes.Core.EventBus
{
    public sealed class EventBus : IEventBus
    {
        private readonly Dictionary<Type, List<Delegate>> handlersByType = new Dictionary<Type, List<Delegate>>();

        public void Subscribe<T>(Action<T> handler)
        {
            if (handler == null)
            {
                return;
            }

            var eventType = typeof(T);
            if (!handlersByType.TryGetValue(eventType, out var handlers))
            {
                handlers = new List<Delegate>();
                handlersByType[eventType] = handlers;
            }

            handlers.Add(handler);
        }

        public void Unsubscribe<T>(Action<T> handler)
        {
            if (handler == null)
            {
                return;
            }

            var eventType = typeof(T);
            if (!handlersByType.TryGetValue(eventType, out var handlers))
            {
                return;
            }

            handlers.Remove(handler);
            if (handlers.Count == 0)
            {
                handlersByType.Remove(eventType);
            }
        }

        public void Publish<T>(T evt)
        {
            var eventType = typeof(T);
            if (!handlersByType.TryGetValue(eventType, out var handlers))
            {
                return;
            }

            var snapshot = handlers.ToArray();
            for (var i = 0; i < snapshot.Length; i++)
            {
                if (snapshot[i] is Action<T> handler)
                {
                    handler(evt);
                }
            }
        }
    }
}
