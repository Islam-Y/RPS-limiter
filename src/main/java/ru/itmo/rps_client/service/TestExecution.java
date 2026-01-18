package ru.itmo.rps_client.service;

import java.net.URI;
import java.time.Duration;
import java.time.Instant;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.atomic.AtomicBoolean;
import ru.itmo.rps_client.config.TestConfig;
import ru.itmo.rps_client.metrics.LoadMetrics;
import ru.itmo.rps_client.profile.LoadProfile;
import ru.itmo.rps_client.scheduler.LoadScheduler;

public class TestExecution {
    private final String testId;
    private final TestConfig config;
    private final URI targetUri;
    private final LoadProfile profile;
    private final LoadScheduler scheduler;
    private final LoadMetrics metrics;
    private final long baseSent;
    private final long baseErrors;
    private final AtomicBoolean running = new AtomicBoolean(false);
    private volatile Instant startTime;
    private volatile Instant endTime;

    public TestExecution(String testId,
                         TestConfig config,
                         URI targetUri,
                         LoadProfile profile,
                         LoadScheduler scheduler,
                         LoadMetrics metrics,
                         long baseSent,
                         long baseErrors) {
        this.testId = testId;
        this.config = config;
        this.targetUri = targetUri;
        this.profile = profile;
        this.scheduler = scheduler;
        this.metrics = metrics;
        this.baseSent = baseSent;
        this.baseErrors = baseErrors;
    }

    public void start() {
        if (!running.compareAndSet(false, true)) {
            return;
        }
        this.startTime = Instant.now();
        metrics.setTestRunning(true);
        scheduler.start(startTime);
        scheduler.completion().whenComplete((ignored, ex) -> {
            running.set(false);
            endTime = Instant.now();
            metrics.setTestRunning(false);
        });
    }

    public void stop() {
        scheduler.stop();
    }

    public boolean isRunning() {
        return running.get();
    }

    public String getTestId() {
        return testId;
    }

    public TestConfig getConfig() {
        return config;
    }

    public URI getTargetUri() {
        return targetUri;
    }

    public LoadProfile getProfile() {
        return profile;
    }

    public Duration getElapsed() {
        Instant end = running.get() ? Instant.now() : (endTime != null ? endTime : Instant.now());
        return startTime == null ? Duration.ZERO : Duration.between(startTime, end);
    }

    public long getRequestsSent() {
        return Math.max(0L, metrics.getTotalSent() - baseSent);
    }

    public long getErrors() {
        return Math.max(0L, metrics.getTotalErrors() - baseErrors);
    }

    public CompletableFuture<Void> completion() {
        return scheduler.completion();
    }
}
