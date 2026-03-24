package ru.itmo.rps_client.http;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.Semaphore;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.ConcurrentMap;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import ru.itmo.rps_client.metrics.LoadMetrics;

public class HttpRequestSender implements RequestSender {
    private static final Logger log = LoggerFactory.getLogger(HttpRequestSender.class);

    private final HttpClient httpClient;
    private final HttpRequest request;
    private final LoadMetrics metrics;
    private final Duration timeout;
    private final Duration slowThreshold;
    private final Semaphore semaphore;
    private final AtomicBoolean stopped = new AtomicBoolean(false);
    private final ConcurrentMap<CompletableFuture<HttpResponse<Void>>, Boolean> inFlight = new ConcurrentHashMap<>();

    public HttpRequestSender(HttpClient httpClient,
                             URI target,
                             LoadMetrics metrics,
                             Duration timeout,
                             Duration slowThreshold,
                             Integer concurrency) {
        this.httpClient = httpClient;
        this.metrics = metrics;
        this.timeout = timeout;
        this.slowThreshold = slowThreshold;
        this.request = HttpRequest.newBuilder(target)
                .timeout(timeout)
                .GET()
                .build();
        this.semaphore = (concurrency != null && concurrency > 0) ? new Semaphore(concurrency) : null;
    }

    @Override
    public void send() {
        if (stopped.get()) {
            return;
        }
        Thread.startVirtualThread(this::dispatchRequest);
    }

    private void dispatchRequest() {
        if (stopped.get()) {
            return;
        }
        try {
            if (semaphore != null) {
                semaphore.acquire();
            }
        } catch (InterruptedException ex) {
            Thread.currentThread().interrupt();
            return;
        }
        if (stopped.get()) {
            if (semaphore != null) {
                semaphore.release();
            }
            return;
        }
        long runId = metrics.currentRunId();
        metrics.recordRequestStart(runId);
        long startNanos = System.nanoTime();
        try {
            CompletableFuture<HttpResponse<Void>> future = httpClient.sendAsync(request, HttpResponse.BodyHandlers.discarding());
            inFlight.put(future, Boolean.TRUE);
            future.whenComplete((response, throwable) -> {
                try {
                    inFlight.remove(future);
                    Duration duration = Duration.ofNanos(System.nanoTime() - startNanos);
                    if (throwable != null || response == null) {
                        logRequestError(response, throwable, duration);
                        metrics.recordRequestError(runId, duration);
                        return;
                    }
                    int status = response.statusCode();
                    if (status >= 200 && status < 300) {
                        logSlowResponse(status, duration);
                        metrics.recordRequestSuccess(runId, duration);
                    } else if (status == 429) {
                        logSlowResponse(status, duration);
                        metrics.recordRequestRateLimited(runId, duration);
                    } else {
                        logRequestError(response, null, duration);
                        metrics.recordRequestError(runId, duration);
                    }
                } finally {
                    if (semaphore != null) {
                        semaphore.release();
                    }
                }
            });
        } catch (Exception ex) {
            Duration duration = Duration.ofNanos(System.nanoTime() - startNanos);
            log.error("Request error target={} message={}", request.uri(), ex.toString());
            metrics.recordRequestError(runId, duration);
            if (semaphore != null) {
                semaphore.release();
            }
        }
    }

    public void stop() {
        stopped.set(true);
        inFlight.keySet().forEach(future -> future.cancel(true));
    }

    private void logRequestError(HttpResponse<Void> response, Throwable throwable, Duration duration) {
        if (throwable != null) {
            log.error("Request error target={} message={}", request.uri(), throwable.toString());
        } else if (response != null) {
            log.error("Request error target={} status={} durationMs={}",
                    request.uri(), response.statusCode(), duration.toMillis());
        } else {
            log.error("Request error target={} durationMs={}", request.uri(), duration.toMillis());
        }
        logSlowResponse(response != null ? response.statusCode() : null, duration);
    }

    private void logSlowResponse(Integer statusCode, Duration duration) {
        if (slowThreshold == null || slowThreshold.isZero() || slowThreshold.isNegative()) {
            return;
        }
        if (duration.compareTo(slowThreshold) >= 0) {
            String status = statusCode == null ? "n/a" : String.valueOf(statusCode);
            log.warn("Slow response target={} status={} durationMs={}",
                    request.uri(), status, duration.toMillis());
        }
    }
}
