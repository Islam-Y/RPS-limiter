package ru.itmo.rate_limiter_service.config;

import java.net.http.HttpClient;
import java.time.Duration;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class HttpClientConfig {
	@Bean
	public HttpClient httpClient() {
		return HttpClient.newBuilder()
			.connectTimeout(Duration.ofSeconds(2))
			.version(HttpClient.Version.HTTP_1_1)
			.build();
	}
}
