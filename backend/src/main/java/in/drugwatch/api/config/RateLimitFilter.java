package in.drugwatch.api.config;

import in.drugwatch.api.shared.PublicNotes;
import in.drugwatch.api.shared.RateLimiter;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.time.Duration;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

/**
 * Rate-limits the public lookups (plan §15: "rate limiting on public endpoints").
 *
 * <p>It applies to the endpoints anybody can call without an account - the batch checker and the
 * drug, manufacturer and alert pages - because those are the ones a script can hammer. The
 * authenticated endpoints are limited by needing a token at all.
 *
 * <p><b>The caller is identified by the socket's remote address, not by {@code
 * X-Forwarded-For}.</b> That header is trivially forged, so trusting it here would hand every
 * caller a way to be a fresh IP on each request - a rate limit that an attacker opts out of is
 * worse than none, because it looks like protection. Phase 12 puts a reverse proxy in front, and
 * that is where {@code server.forward-headers-strategy} belongs: once, at a boundary that can
 * actually be trusted.
 */
@Component
public class RateLimitFilter extends OncePerRequestFilter {

    private static final Duration WINDOW = Duration.ofMinutes(1);

    private final RateLimiter limiter;
    private final int perMinute;

    RateLimitFilter(RateLimiter limiter, @Value("${drugwatch.rate-limit.per-minute:60}") int perMinute) {
        this.limiter = limiter;
        this.perMinute = perMinute;
    }

    @Override
    protected boolean shouldNotFilter(HttpServletRequest request) {
        String path = request.getRequestURI();
        return !(path.startsWith("/api/v1/batches/")
                || path.startsWith("/api/v1/drugs/")
                || path.startsWith("/api/v1/manufacturers/")
                || path.startsWith("/api/v1/alerts/")
                // Plan §9 step 10 names this one specifically: it mints a credential and makes an
                // outbound call to Superset per request, so it is the easiest endpoint here to
                // turn into a denial of service against a third service.
                || path.startsWith("/api/v1/dashboards"));
    }

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain chain)
            throws ServletException, IOException {
        RateLimiter.Decision decision = limiter.check(request.getRemoteAddr(), perMinute, WINDOW);

        // Sent on every response, allowed or not: a client that can see its own budget can slow
        // down on its own, which is better for both sides than being cut off at the limit.
        response.setHeader("X-RateLimit-Limit", String.valueOf(perMinute));
        response.setHeader("X-RateLimit-Remaining", String.valueOf(decision.remaining()));

        if (decision.allowed()) {
            chain.doFilter(request, response);
            return;
        }

        response.setStatus(HttpStatus.TOO_MANY_REQUESTS.value());
        response.setHeader(
                HttpHeaders.RETRY_AFTER, String.valueOf(decision.retryAfter().toSeconds()));
        response.setContentType(MediaType.APPLICATION_JSON_VALUE);
        response.getWriter().write("""
                        {"status":429,"error":"Too many requests. Please wait %d seconds and try again.",\
                        "detail":{"retryAfterSeconds":%d},"disclaimer":"%s"}""".formatted(
                        decision.retryAfter().toSeconds(), decision.retryAfter().toSeconds(), PublicNotes.DISCLAIMER));
    }
}
