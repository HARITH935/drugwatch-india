package in.drugwatch.api.watchlist.api;

import in.drugwatch.api.watchlist.domain.WatchlistService;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;
import java.util.List;
import java.util.Map;
import org.springframework.http.HttpStatus;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;

/**
 * Plan §10's watchlist endpoints. Every one is scoped to the caller.
 *
 * <p>The user id comes from the verified token's subject, never from the request. A watchlist that
 * took a user id as a parameter would let anybody read or delete anybody's watches by changing a
 * number, and no amount of validation fixes that shape.
 */
@RestController
@RequestMapping("/api/v1/watchlist")
public class WatchlistController {

    private final WatchlistService watchlist;

    WatchlistController(WatchlistService watchlist) {
        this.watchlist = watchlist;
    }

    @GetMapping
    public Map<String, Object> list(@AuthenticationPrincipal Jwt token) {
        List<WatchlistService.Watch> watches = watchlist.list(userId(token));
        return Map.of(
                "watches",
                watches,
                "note",
                "A watch matches the medicine name printed in CDSCO's alerts, as a whole word. You"
                        + " are emailed about alert months published after you added it - the medicine"
                        + " pages show what was reported before that.");
    }

    @PostMapping
    @ResponseStatus(HttpStatus.CREATED)
    public WatchlistService.Watch add(@AuthenticationPrincipal Jwt token, @Valid @RequestBody AddRequest request) {
        return watchlist.add(userId(token), request.term());
    }

    @DeleteMapping("/{id}")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public void remove(@AuthenticationPrincipal Jwt token, @PathVariable Long id) {
        watchlist.remove(userId(token), id);
    }

    /** The subject claim of a signature-verified token. */
    private static Long userId(Jwt token) {
        return Long.valueOf(token.getSubject());
    }

    public record AddRequest(
            @NotBlank @Size(min = 3, max = 100) String term) {}
}
