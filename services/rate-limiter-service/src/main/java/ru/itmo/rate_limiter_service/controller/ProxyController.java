package ru.itmo.rate_limiter_service.controller;

import jakarta.servlet.http.HttpServletRequest;
import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.util.Enumeration;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import lombok.RequiredArgsConstructor;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestMethod;
import org.springframework.web.bind.annotation.RestController;
import ru.itmo.rate_limiter_service.config.RateLimiterProperties;
import ru.itmo.rate_limiter_service.metrics.RateLimiterMetrics;
import ru.itmo.rate_limiter_service.metrics.TrafficStats;
import ru.itmo.rate_limiter_service.model.RateLimiterConfig;
import ru.itmo.rate_limiter_service.service.RateLimiter;
import ru.itmo.rate_limiter_service.service.RateLimiterConfigService;

@RestController
@RequiredArgsConstructor
public class ProxyController {
	private static final Logger log = LoggerFactory.getLogger(ProxyController.class);
	private static final Set<String> HOP_BY_HOP_HEADERS = Set.of(
		"connection",
		"keep-alive",
		"proxy-authenticate",
		"proxy-authorization",
		"te",
		"trailer",
		"transfer-encoding",
		"upgrade",
		"host"
	);

	private final RateLimiter rateLimiter;
	private final RateLimiterConfigService configService;
	private final RateLimiterMetrics metrics;
	private final TrafficStats trafficStats;
	private final RateLimiterProperties properties;
	private final HttpClient httpClient;

	@RequestMapping(
		value = "/**",
		method = {
			RequestMethod.GET,
			RequestMethod.POST,
			RequestMethod.PUT,
			RequestMethod.DELETE,
			RequestMethod.PATCH,
			RequestMethod.HEAD,
			RequestMethod.OPTIONS
		}
	)
	public ResponseEntity<byte[]> proxy(HttpServletRequest request) {
		RateLimiterConfig config = configService.getCurrent();
		var sample = metrics.startRequestTimer();
		boolean allowed = rateLimiter.allow(config);
		if (!allowed) {
			metrics.incrementDecision(config.getAlgorithm(), false);
			trafficStats.recordDecision(false, 429);
			metrics.stopRequestTimer(sample);
			return ResponseEntity.status(429)
				.contentType(MediaType.TEXT_PLAIN)
				.body("Rate limit exceeded".getBytes(StandardCharsets.UTF_8));
		}

		try {
			HttpRequest outbound = buildOutboundRequest(request);
			HttpResponse<byte[]> response = httpClient.send(outbound, HttpResponse.BodyHandlers.ofByteArray());
			metrics.incrementDecision(config.getAlgorithm(), true);
			trafficStats.recordDecision(true, response.statusCode());
			metrics.stopRequestTimer(sample);
			return toResponseEntity(response);
		} catch (Exception ex) {
			if (ex instanceof InterruptedException) {
				Thread.currentThread().interrupt();
			}
			metrics.incrementDecision(config.getAlgorithm(), true);
			trafficStats.recordDecision(true, 502);
			metrics.stopRequestTimer(sample);
			log.error("Proxy request failed: {}", ex.getMessage());
			return ResponseEntity.status(502)
				.contentType(MediaType.TEXT_PLAIN)
				.body("Upstream error".getBytes(StandardCharsets.UTF_8));
		}
	}

	private HttpRequest buildOutboundRequest(HttpServletRequest request) throws IOException {
		String targetUrl = buildTargetUrl(request);
		HttpRequest.Builder builder = HttpRequest.newBuilder()
			.uri(URI.create(targetUrl))
			.method(request.getMethod(), bodyPublisher(request));

		copyRequestHeaders(request, builder);
		String remoteAddr = request.getRemoteAddr();
		if (remoteAddr != null && !remoteAddr.isEmpty()) {
			builder.header("X-Forwarded-For", remoteAddr);
		}
		return builder.build();
	}

	private HttpRequest.BodyPublisher bodyPublisher(HttpServletRequest request) throws IOException {
		byte[] body = request.getInputStream().readAllBytes();
		if (body.length == 0) {
			return HttpRequest.BodyPublishers.noBody();
		}
		return HttpRequest.BodyPublishers.ofByteArray(body);
	}

	private void copyRequestHeaders(HttpServletRequest request, HttpRequest.Builder builder) {
		Enumeration<String> headerNames = request.getHeaderNames();
		while (headerNames.hasMoreElements()) {
			String header = headerNames.nextElement();
			if (isHopByHopHeader(header)) {
				continue;
			}
			Enumeration<String> values = request.getHeaders(header);
			while (values.hasMoreElements()) {
				builder.header(header, values.nextElement());
			}
		}
	}

	private ResponseEntity<byte[]> toResponseEntity(HttpResponse<byte[]> response) {
		HttpHeaders headers = new HttpHeaders();
		for (Map.Entry<String, java.util.List<String>> entry : response.headers().map().entrySet()) {
			String header = entry.getKey();
			if (isHopByHopHeader(header)) {
				continue;
			}
			headers.put(header, entry.getValue());
		}
		return ResponseEntity.status(response.statusCode())
			.headers(headers)
			.body(response.body());
	}

	private boolean isHopByHopHeader(String header) {
		return HOP_BY_HOP_HEADERS.contains(header.toLowerCase(Locale.ROOT));
	}

	private String buildTargetUrl(HttpServletRequest request) {
		String base = properties.getTargetUrl();
		String path = request.getRequestURI();
		if (base.endsWith("/")) {
			base = base.substring(0, base.length() - 1);
		}
		if (!path.startsWith("/")) {
			path = "/" + path;
		}
		StringBuilder target = new StringBuilder(base).append(path);
		String query = request.getQueryString();
		if (query != null && !query.isEmpty()) {
			target.append('?').append(query);
		}
		return target.toString();
	}
}
