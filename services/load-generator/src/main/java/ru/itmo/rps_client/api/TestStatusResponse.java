package ru.itmo.rps_client.api;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.databind.JsonNode;

@JsonInclude(JsonInclude.Include.NON_NULL)
public record TestStatusResponse(
        boolean running,
        String testId,
        String profile,
        String targetUrl,
        JsonNode profileParams,
        Integer concurrency,
        Long elapsedTime,
        Long duration,
        Long requestsSent,
        Long errors
) {
    public static TestStatusResponse notRunning() {
        return new TestStatusResponse(false, null, null, null, null, null, null, null, null, null);
    }

    public static TestStatusResponse running(String testId,
                                             String profile,
                                             String targetUrl,
                                             JsonNode profileParams,
                                             Integer concurrency,
                                             long elapsedTime,
                                             long duration,
                                             long requestsSent,
                                             long errors) {
        return new TestStatusResponse(true, testId, profile, targetUrl, profileParams, concurrency,
                elapsedTime, duration, requestsSent, errors);
    }
}
