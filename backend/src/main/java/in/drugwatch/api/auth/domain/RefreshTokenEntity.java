package in.drugwatch.api.auth.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import java.time.Instant;

/** One refresh token, stored as a hash (see {@link TokenHash}). */
@Entity
@Table(name = "refresh_tokens")
class RefreshTokenEntity {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "user_id", nullable = false)
    private Long userId;

    @Column(name = "token_hash", nullable = false, unique = true)
    private String tokenHash;

    @Column(name = "expires_at", nullable = false)
    private Instant expiresAt;

    /**
     * Set when the token is used or logged out, rather than deleting the row. A token presented a
     * second time is worth being able to see - it means the first one was copied - and a deleted
     * row cannot tell anybody that.
     */
    @Column(name = "revoked_at")
    private Instant revokedAt;

    @Column(name = "created_at", nullable = false, insertable = false, updatable = false)
    private Instant createdAt;

    protected RefreshTokenEntity() {}

    RefreshTokenEntity(Long userId, String tokenHash, Instant expiresAt) {
        this.userId = userId;
        this.tokenHash = tokenHash;
        this.expiresAt = expiresAt;
    }

    Long getUserId() {
        return userId;
    }

    boolean isUsable(Instant now) {
        return revokedAt == null && expiresAt.isAfter(now);
    }

    boolean isRevoked() {
        return revokedAt != null;
    }

    void revoke(Instant now) {
        this.revokedAt = now;
    }
}
