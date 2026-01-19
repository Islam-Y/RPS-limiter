package ru.itmo.application_service.controller;

import io.micrometer.core.annotation.Timed;
import java.util.concurrent.atomic.AtomicLong;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import ru.itmo.application_service.config.AppProperties;

@RestController
@RequestMapping("/api")
public class TargetController {
	private static final Logger log = LoggerFactory.getLogger(TargetController.class);

	private final AppProperties properties;
	private final AtomicLong requestCounter = new AtomicLong();

	public TargetController(AppProperties properties) {
		this.properties = properties;
	}

	@Timed(value = "service_b_test", description = "Time spent processing /api/test")
	@GetMapping("/test")
	public ResponseEntity<String> test() {
		long requestId = requestCounter.incrementAndGet();
		if (properties.isLogPerRequest()) {
			log.info("Request {} received", requestId);
		}
		applyProcessingDelay();
		if (properties.isLogPerRequest()) {
			log.info("Request {} completed", requestId);
		}
		return ResponseEntity.ok("OK");
	}

	private void applyProcessingDelay() {
		long delayMs = properties.getProcessingDelayMs();
		if (delayMs <= 0) {
			return;
		}
		try {
			Thread.sleep(delayMs);
		} catch (InterruptedException ex) {
			Thread.currentThread().interrupt();
			throw new IllegalStateException("Interrupted while simulating processing", ex);
		}
	}
}
