# =============================================================================
# CloudFront in front of the API (api.<domain>)
# =============================================================================
# The ALB is in us-east-1 and terminates TLS itself, so every viewer paid a
# full cross-region handshake before the first byte: measured ~0.55s of TLS
# alone from Tokyo, on top of ~0.2s round-trip. That dwarfed the actual server
# time once the read cache landed. CloudFront terminates TLS at the edge and
# serves repeat requests from there.
#
# Origin hostname: CloudFront validates the origin's certificate against the
# origin domain name, so it cannot use the ALB's own *.elb.amazonaws.com name
# (the cert covers moundmodel.com names) and it cannot use api.<domain> either
# — that is about to become this distribution's own alias, which would loop.
# Hence a dedicated api-origin.<domain> with its own certificate, attached to
# the existing listener as an extra SNI cert. The main site certificate is left
# untouched: adding a SAN to it would force a replacement and briefly churn the
# cert on the live site distribution and the ALB listener.
# =============================================================================

resource "aws_acm_certificate" "api_origin" {
  domain_name       = "api-origin.${var.site_domain}"
  validation_method = "DNS"
  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_route53_record" "api_origin_cert_validation" {
  for_each = {
    for dvo in aws_acm_certificate.api_origin.domain_validation_options :
    dvo.domain_name => {
      name   = dvo.resource_record_name
      type   = dvo.resource_record_type
      record = dvo.resource_record_value
    }
  }
  zone_id = data.aws_route53_zone.site.zone_id
  name    = each.value.name
  type    = each.value.type
  ttl     = 300
  records = [each.value.record]
}

resource "aws_acm_certificate_validation" "api_origin" {
  certificate_arn         = aws_acm_certificate.api_origin.arn
  validation_record_fqdns = [for r in aws_route53_record.api_origin_cert_validation : r.fqdn]
}

# The ALB picks this by SNI, so direct hits to the ALB on the original
# api.<domain> certificate keep working — useful for bypassing the CDN when
# debugging whether a problem is CloudFront's or the origin's.
resource "aws_lb_listener_certificate" "api_origin" {
  listener_arn    = aws_lb_listener.api_https.arn
  certificate_arn = aws_acm_certificate_validation.api_origin.certificate_arn
}

resource "aws_route53_record" "api_origin" {
  zone_id = data.aws_route53_zone.site.zone_id
  name    = "api-origin.${var.site_domain}"
  type    = "A"
  alias {
    name                   = aws_lb.api.dns_name
    zone_id                = aws_lb.api.zone_id
    evaluate_target_health = false
  }
}

# Origin MUST be in the cache key. The API echoes the caller's origin back in
# access-control-allow-origin (ALLOWED_ORIGINS is apex + www, not "*") and sets
# Vary: Origin accordingly — so a shared cache that ignored the header could
# hand a www visitor a response that only permits the apex, and the browser
# would reject it. Query strings likewise: every endpoint is parameterised by
# ?days=/?date=/?teams=, and the managed CachingOptimized policy strips them.
resource "aws_cloudfront_cache_policy" "api" {
  name    = "${var.project}-api"
  comment = "Public read API: vary on query strings + Origin, honour origin Cache-Control"

  # The origin sends Cache-Control: max-age=60, which CloudFront honours
  # because it falls inside [min_ttl, max_ttl]. default_ttl only applies if the
  # origin ever stops sending a Cache-Control header.
  min_ttl     = 0
  default_ttl = 60
  max_ttl     = 600

  parameters_in_cache_key_and_forwarded_to_origin {
    enable_accept_encoding_gzip   = true
    enable_accept_encoding_brotli = true

    query_strings_config {
      query_string_behavior = "all"
    }
    headers_config {
      header_behavior = "whitelist"
      headers {
        items = ["Origin"]
      }
    }
    cookies_config {
      cookie_behavior = "none"
    }
  }
}

resource "aws_cloudfront_distribution" "api" {
  enabled = true
  aliases = ["api.${var.site_domain}"]
  comment = "${var.project} public API"

  # PriceClass_100 (what the site distribution uses) excludes Asian edges, so a
  # Tokyo viewer would be served from the US or Europe and the handshake saving
  # would largely evaporate. _200 adds Japan; the site is bilingual EN/JA and
  # its readers are the reason this distribution exists.
  price_class = "PriceClass_200"

  logging_config {
    bucket          = aws_s3_bucket.logs.bucket_domain_name
    prefix          = "cf-api/"
    include_cookies = false
  }

  origin {
    domain_name = "api-origin.${var.site_domain}"
    origin_id   = "alb-api"
    custom_origin_config {
      http_port                = 80
      https_port               = 443
      origin_protocol_policy   = "https-only"
      origin_ssl_protocols     = ["TLSv1.2"]
      origin_read_timeout      = 30
      origin_keepalive_timeout = 60
    }
  }

  default_cache_behavior {
    target_origin_id       = "alb-api"
    viewer_protocol_policy = "redirect-to-https"
    # OPTIONS is allowed but not cached: today's calls are simple GETs that
    # trigger no preflight, but a future custom header would 405 without it.
    allowed_methods = ["GET", "HEAD", "OPTIONS"]
    cached_methods  = ["GET", "HEAD"]
    compress        = true
    cache_policy_id = aws_cloudfront_cache_policy.api.id
  }

  # Health must never be served from cache — a cached 200 would keep reporting
  # healthy after the origin had died.
  ordered_cache_behavior {
    path_pattern           = "/api/health"
    target_origin_id       = "alb-api"
    viewer_protocol_policy = "https-only"
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    cache_policy_id        = "4135ea2d-6df8-44a3-9df3-4b5a84be39ad" # CachingDisabled
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  # Same certificate as the site: it already carries api.<domain> as a SAN.
  viewer_certificate {
    acm_certificate_arn      = aws_acm_certificate_validation.site.certificate_arn
    ssl_support_method       = "sni-only"
    minimum_protocol_version = "TLSv1.2_2021"
  }
}

output "api_cdn_domain" {
  description = "CloudFront domain for the API; test here before flipping DNS"
  value       = aws_cloudfront_distribution.api.domain_name
}

output "api_cdn_id" {
  description = "Distribution id, for invalidations"
  value       = aws_cloudfront_distribution.api.id
}
