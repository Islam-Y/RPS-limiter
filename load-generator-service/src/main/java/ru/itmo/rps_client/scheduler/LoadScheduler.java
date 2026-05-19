package ru.itmo.rps_client.scheduler;

import java.time.Instant;
import java.util.concurrent.CompletableFuture;

public interface LoadScheduler {
    void start(Instant startTime);

    void stop();

    boolean isRunning();

    CompletableFuture<Void> completion();
}
