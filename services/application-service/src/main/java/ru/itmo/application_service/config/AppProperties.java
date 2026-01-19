package ru.itmo.application_service.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "app")
public class AppProperties {
	private long processingDelayMs = 0;
	private boolean logPerRequest = true;

	public long getProcessingDelayMs() {
		return processingDelayMs;
	}

	public void setProcessingDelayMs(long processingDelayMs) {
		this.processingDelayMs = processingDelayMs;
	}

	public boolean isLogPerRequest() {
		return logPerRequest;
	}

	public void setLogPerRequest(boolean logPerRequest) {
		this.logPerRequest = logPerRequest;
	}
}
