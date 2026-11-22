package in.drugwatch.api.config;

import javax.crypto.spec.SecretKeySpec;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.HttpMethod;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.security.oauth2.jose.jws.MacAlgorithm;
import org.springframework.security.oauth2.jwt.JwtDecoder;
import org.springframework.security.oauth2.jwt.NimbusJwtDecoder;
import org.springframework.security.web.SecurityFilterChain;

/**
 * Who may call what.
 *
 * <p>Two principles, both of which the tests check rather than assume:
 *
 * <ul>
 *   <li><b>Public things are listed; everything else needs a token.</b> The default is deny, so a
 *       new endpoint is protected until somebody deliberately opens it. The opposite default -
 *       "permit unless listed" - ships an unprotected endpoint the first time somebody forgets.
 *   <li><b>No sessions.</b> The API is stateless; a token is presented on every request. That is
 *       also why CSRF protection is off: there is no cookie for a browser to send automatically,
 *       so there is nothing for a cross-site request to ride on.
 * </ul>
 */
@Configuration
public class SecurityConfig {

    @Bean
    SecurityFilterChain filterChain(HttpSecurity http) throws Exception {
        http.csrf(csrf -> csrf.disable())
                .sessionManagement(session -> session.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
                .authorizeHttpRequests(requests -> requests
                        // The public data. This is a public-interest site: the batch checker and
                        // the drug and manufacturer pages must work without an account.
                        .requestMatchers(HttpMethod.GET, "/api/v1/batches/**", "/api/v1/drugs/**")
                        .permitAll()
                        .requestMatchers(HttpMethod.GET, "/api/v1/manufacturers/**", "/api/v1/alerts/**")
                        .permitAll()
                        // Registering, logging in, refreshing and verifying an email all happen
                        // before there is a token to present.
                        .requestMatchers("/api/v1/auth/**")
                        .permitAll()
                        .requestMatchers("/actuator/health")
                        .permitAll()
                        // Everything else, including the watchlist and anything added later.
                        .anyRequest()
                        .authenticated())
                .oauth2ResourceServer(oauth2 -> oauth2.jwt(jwt -> {}));
        return http.build();
    }

    /**
     * BCrypt (plan §15). Deliberately slow, so that guessing a human-chosen password costs the
     * attacker time per attempt - the opposite of what is wanted for a random token.
     */
    @Bean
    PasswordEncoder passwordEncoder() {
        return new BCryptPasswordEncoder();
    }

    @Bean
    JwtDecoder jwtDecoder(@Value("${drugwatch.auth.jwt-secret}") String secret) {
        return NimbusJwtDecoder.withSecretKey(new SecretKeySpec(secret.getBytes(), "HmacSHA256"))
                .macAlgorithm(MacAlgorithm.HS256)
                .build();
    }
}
