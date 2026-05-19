package ru.itmo.rate_limiter_service.config;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.web.client.RestTemplate;

@Configuration
public class RestTemplateConfig {
	@Bean
	public RestTemplate restTemplate(RateLimiterProperties properties) {
		SimpleClientHttpRequestFactory factory = new SimpleClientHttpRequestFactory();
		int timeoutMs = (int) properties.getAdaptive().getTimeout().toMillis();
		factory.setConnectTimeout(timeoutMs);
		factory.setReadTimeout(timeoutMs);
		return new RestTemplate(factory);
	}
}
