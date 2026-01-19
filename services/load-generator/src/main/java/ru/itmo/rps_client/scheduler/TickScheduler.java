package ru.itmo.rps_client.scheduler;

import java.time.Duration;
import java.time.Instant;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import ru.itmo.rps_client.http.RequestSender;
import ru.itmo.rps_client.profile.LoadProfile;

public class TickScheduler implements LoadScheduler {
    private final Duration duration;
    private final Duration tick;
    private final LoadProfile profile;
    private final RequestSender sender;
    private final ScheduledExecutorService scheduler;
    private final AtomicBoolean running = new AtomicBoolean(false);
    private final AtomicBoolean finished = new AtomicBoolean(false);
    private final CompletableFuture<Void> completion = new CompletableFuture<>();
    private volatile Instant startTime;
    private volatile ScheduledFuture<?> future;
    private double carryOver = 0.0;

    public TickScheduler(Duration duration, Duration tick, LoadProfile profile, RequestSender sender) {
        this.duration = duration;
        this.tick = tick.isNegative() || tick.isZero() ? Duration.ofMillis(100) : tick;
        this.profile = profile;
        this.sender = sender;
        this.scheduler = Executors.newSingleThreadScheduledExecutor(r -> {
            Thread thread = new Thread(r, "loadgen-tick");
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
        long tickMillis = Math.max(1L, tick.toMillis());
        future = scheduler.scheduleAtFixedRate(this::onTick, 0, tickMillis, TimeUnit.MILLISECONDS);
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

    private void onTick() {
        if (!running.get()) {
            return;
        }
        try {
            Duration elapsed = Duration.between(startTime, Instant.now());
            if (elapsed.compareTo(duration) >= 0) {
                finish();
                return;
            }
            double rps = Math.max(0.0, profile.currentRps(elapsed));
            double expected = rps * (tick.toMillis() / 1000.0) + carryOver;
            int toSend = (int) Math.floor(expected);
            carryOver = expected - toSend;
            for (int i = 0; i < toSend; i++) {
                sender.send();
            }
        } catch (Exception ex) {
            completion.completeExceptionally(ex);
            finish();
        }
    }

    private void finish() {
        if (!finished.compareAndSet(false, true)) {
            return;
        }
        running.set(false);
        if (future != null) {
            future.cancel(false);
        }
        scheduler.shutdownNow();
        completion.complete(null);
    }
}
