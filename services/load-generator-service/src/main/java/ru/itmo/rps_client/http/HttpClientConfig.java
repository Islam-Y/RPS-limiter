package ru.itmo.rps_client.http;

import java.net.http.HttpClient;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import ru.itmo.rps_client.config.LoadGeneratorProperties;

@Configuration
public class HttpClientConfig {
    @Bean
    public HttpClient httpClient(LoadGeneratorProperties properties) {
        return HttpClient.newBuilder()
                .connectTimeout(properties.getHttp().getConnectTimeout())
                .version(HttpClient.Version.HTTP_1_1)
                .build();
    }
}
