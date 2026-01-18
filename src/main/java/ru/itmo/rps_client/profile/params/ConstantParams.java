package ru.itmo.rps_client.profile.params;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;

@JsonIgnoreProperties(ignoreUnknown = true)
public record ConstantParams(double rps) {
}
