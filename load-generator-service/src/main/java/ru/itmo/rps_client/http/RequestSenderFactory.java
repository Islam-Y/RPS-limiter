package ru.itmo.rps_client.http;

import java.net.URI;
import java.net.http.HttpClient;
import org.springframework.stereotype.Component;
import ru.itmo.rps_client.config.LoadGeneratorProperties;
import ru.itmo.rps_client.metrics.LoadMetrics;

@Component
public class RequestSenderFactory {
    private final HttpClient httpClient;
    private final LoadGeneratorProperties properties;
    private final LoadMetrics metrics;

    public RequestSenderFactory(HttpClient httpClient, LoadGeneratorProperties properties, LoadMetrics metrics) {
        this.httpClient = httpClient;
        this.properties = properties;
        this.metrics = metrics;
    }

    public HttpRequestSender create(URI target, Integer concurrency) {
        int effectiveConcurrency = concurrency != null ? concurrency : properties.getDefaultConcurrency();
        Integer limit = effectiveConcurrency > 0 ? effectiveConcurrency : null;
        return new HttpRequestSender(httpClient, target, metrics, properties.getHttp().getTimeout(),
                properties.getHttp().getSlowThreshold(), limit);
    }
}
