package ru.itmo.rps_client.scheduler;

import java.time.Duration;
import java.time.Instant;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.locks.LockSupport;
import ru.itmo.rps_client.http.RequestSender;
import ru.itmo.rps_client.profile.LoadProfile;

public class IntervalScheduler implements LoadScheduler {
    private final Duration duration;
    private final Duration idleDelay;
    private final LoadProfile profile;
    private final RequestSender sender;
    private final ExecutorService executor;
    private final AtomicBoolean running = new AtomicBoolean(false);
    private final AtomicBoolean finished = new AtomicBoolean(false);
    private final CompletableFuture<Void> completion = new CompletableFuture<>();
    private volatile Instant startTime;

    public IntervalScheduler(Duration duration, Duration idleDelay, LoadProfile profile, RequestSender sender) {
        this.duration = duration;
        this.idleDelay = sanitizeDelay(idleDelay);
        this.profile = profile;
        this.sender = sender;
        this.executor = Executors.newSingleThreadExecutor(r -> {
            Thread thread = new Thread(r, "loadgen-interval");
            thread.setDaemon(true);
            return thread;
        });
    }

    @Override
    public void start(Instant startTime) {
        if (!running.compareAndSet(false, true)) {
            return;
        }
        this.startTime = startTime;
        executor.submit(this::runLoop);
    }

    @Override
    public void stop() {
        finish();
    }

    @Override
    public boolean isRunning() {
        return running.get();
    }

    @Override
    public CompletableFuture<Void> completion() {
        return completion;
    }

    private void runLoop() {
        try {
            while (running.get()) {
                Duration elapsed = Duration.between(startTime, Instant.now());
                if (elapsed.compareTo(duration) >= 0) {
                    finish();
                    return;
                }
                double rps = profile.currentRps(elapsed);
                if (rps <= 0.0) {
                    if (!idleDelay.isZero() && !idleDelay.isNegative()) {
                        sleep(idleDelay);
                    }
                    continue;
                }
                Duration delay = profile.nextDelay(elapsed);
                if (!delay.isZero() && !delay.isNegative()) {
                    sleep(delay);
                }
                if (!running.get()) {
                    return;
                }
                Duration afterSleep = Duration.between(startTime, Instant.now());
                if (afterSleep.compareTo(duration) >= 0) {
                    finish();
                    return;
                }
                sender.send();
            }
        } catch (Exception ex) {
            completion.completeExceptionally(ex);
            finish();
        }
    }

    private void sleep(Duration delay) throws InterruptedException {
        long nanos = delay.toNanos();
        long deadline = System.nanoTime() + nanos;
        while (nanos > 0 && running.get()) {
            LockSupport.parkNanos(nanos);
            if (Thread.interrupted()) {
                throw new InterruptedException("Interval scheduler interrupted");
            }
            nanos = deadline - System.nanoTime();
        }
    }

    private void finish() {
        if (!finished.compareAndSet(false, true)) {
            return;
        }
        running.set(false);
        executor.shutdownNow();
        completion.complete(null);
    }

    private static Duration sanitizeDelay(Duration delay) {
        if (delay == null || delay.isZero() || delay.isNegative()) {
            return Duration.ofMillis(100);
        }
        return delay;
    }
}
