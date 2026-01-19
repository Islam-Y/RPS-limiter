package ru.itmo.rps_client.metrics;

import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.Gauge;
import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.Timer;
import jakarta.annotation.PreDestroy;
import java.time.Duration;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;
import org.springframework.stereotype.Component;

@Component
public class LoadMetrics {
    private final MeterRegistry registry;
    private Counter successCounter;
    private Counter errorCounter;
    private Timer latencyTimer;
    private final AtomicLong totalSent = new AtomicLong();
    private final AtomicLong totalErrors = new AtomicLong();
    private final AtomicInteger inFlight = new AtomicInteger();
    private final AtomicLong currentRps = new AtomicLong();
    private final AtomicLong currentSecondCount = new AtomicLong();
    private final AtomicBoolean testRunning = new AtomicBoolean(false);
    private final AtomicLong runId = new AtomicLong();
    private final ScheduledExecutorService scheduler = Executors.newSingleThreadScheduledExecutor(r -> {
        Thread thread = new Thread(r, "loadgen-metrics");
        thread.setDaemon(true);
        return thread;
    });

    public LoadMetrics(MeterRegistry registry) {
        this.registry = registry;
        registerCounters();
        registerGauges();
        scheduler.scheduleAtFixedRate(this::rollRps, 1, 1, TimeUnit.SECONDS);
    }

    public void resetForNewTest() {
        runId.incrementAndGet();
        removeCounters();
        totalSent.set(0);
        totalErrors.set(0);
        currentSecondCount.set(0);
        currentRps.set(0);
        inFlight.set(0);
        registerCounters();
    }

    public long currentRunId() {
        return runId.get();
    }

    public void recordRequestStart(long runId) {
        if (runId != this.runId.get()) {
            return;
        }
        totalSent.incrementAndGet();
        currentSecondCount.incrementAndGet();
        inFlight.incrementAndGet();
    }

    public void recordRequestSuccess(long runId, Duration duration) {
        if (runId != this.runId.get()) {
            return;
        }
        successCounter.increment();
        latencyTimer.record(duration);
        inFlight.decrementAndGet();
    }

    public void recordRequestError(long runId, Duration duration) {
        if (runId != this.runId.get()) {
            return;
        }
        errorCounter.increment();
        totalErrors.incrementAndGet();
        latencyTimer.record(duration);
        inFlight.decrementAndGet();
    }

    public void setTestRunning(boolean running) {
        testRunning.set(running);
    }

    public long getTotalSent() {
        return totalSent.get();
    }

    public long getTotalErrors() {
        return totalErrors.get();
    }

    public long getCurrentRps() {
        return currentRps.get();
    }

    private void rollRps() {
        currentRps.set(currentSecondCount.getAndSet(0));
    }

    private void registerCounters() {
        successCounter = Counter.builder("loadgen_requests_total")
                .description("Total HTTP requests sent by load generator")
                .tag("status", "success")
                .register(registry);
        errorCounter = Counter.builder("loadgen_requests_total")
                .description("Total HTTP requests sent by load generator")
                .tag("status", "error")
                .register(registry);
        latencyTimer = Timer.builder("loadgen_request_duration")
                .description("HTTP request latency in seconds")
                .publishPercentileHistogram()
                .serviceLevelObjectives(
                        Duration.ofMillis(10),
                        Duration.ofMillis(50),
                        Duration.ofMillis(100),
                        Duration.ofMillis(200),
                        Duration.ofMillis(500),
                        Duration.ofSeconds(1),
                        Duration.ofSeconds(2),
                        Duration.ofSeconds(5)
                )
                .register(registry);
    }

    private void registerGauges() {
        Gauge.builder("loadgen_current_rps", currentRps, AtomicLong::get)
                .description("Current requests per second")
                .register(registry);
        Gauge.builder("loadgen_active_threads", inFlight, AtomicInteger::get)
                .description("Number of active in-flight requests")
                .register(registry);
        Gauge.builder("loadgen_test_running", testRunning, value -> value.get() ? 1 : 0)
                .description("Whether a load test is currently running")
                .register(registry);
    }

    private void removeCounters() {
        if (successCounter != null) {
            registry.remove(successCounter);
        }
        if (errorCounter != null) {
            registry.remove(errorCounter);
        }
        if (latencyTimer != null) {
            registry.remove(latencyTimer);
        }
    }

    @PreDestroy
    public void shutdown() {
        scheduler.shutdownNow();
    }
}
