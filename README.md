## Event Streaming Backbone — Stage 3

`DeduplicatingSubscriber` is the reusable subscriber boundary for at-least-once delivery. It suppresses previously processed message IDs/sequences and records delivery only after the wrapped callback succeeds. A failed callback remains retryable. The supplied repository does not contain the real `HistoryStore` implementation, so no fictitious end-to-end HistoryStore migration is claimed here.
