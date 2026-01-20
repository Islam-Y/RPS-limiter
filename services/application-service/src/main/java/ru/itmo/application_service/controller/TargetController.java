package ru.itmo.application_service.controller;

import io.micrometer.core.annotation.Timed;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import ru.itmo.application_service.config.AppProperties;

@RestController
@RequestMapping("/api")
@RequiredArgsConstructor
public class TargetController {
	private final AppProperties properties;

	@Timed(value = "service_b_test", description = "Time spent processing /api/test")
	@GetMapping("/test")
	public ResponseEntity<String> test() {
		applyProcessingDelay();
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
