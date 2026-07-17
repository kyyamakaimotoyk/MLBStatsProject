# =============================================================================
# Analytics foundation: Athena over the CloudFront logs
# =============================================================================
# Athena reads files in S3 via a Glue TABLE that describes their format. We
# define that table (and its database + an Athena workgroup with a results
# location) in Terraform so it's reproducible. The consumer is the local-only
# dashboard in visualization/site_traffic.py.
#
# The data: CloudFront access logs delivered to the logs bucket under cf-site/
# (cf_logs.tf). Standard CloudFront log format = 33 tab-separated columns with
# two leading "#"-comment lines we skip.
#
# Note: the table is unpartitioned, so each query scans every log file. At this
# site's volume that's a few MB (a fraction of a cent per query); add partition
# projection here if traffic ever grows large.
# =============================================================================


# Glue Data Catalog = the metastore Athena uses. A "database" is just a namespace.
resource "aws_glue_catalog_database" "logs" {
  name = "moundmodel_logs"
}


# The table describing the CloudFront log files.
resource "aws_glue_catalog_table" "cf_site_logs" {
  name          = "cf_site_logs"
  database_name = aws_glue_catalog_database.logs.name
  table_type    = "EXTERNAL_TABLE"

  parameters = {
    EXTERNAL                 = "TRUE"
    "skip.header.line.count" = "2" # CloudFront's #Version and #Fields lines
  }

  storage_descriptor {
    location      = "s3://${aws_s3_bucket.logs.bucket}/cf-site/"
    input_format  = "org.apache.hadoop.mapred.TextInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat"

    ser_de_info {
      serialization_library = "org.apache.hadoop.hive.serde2.lazy.LazySimpleSerDe"
      parameters = {
        "field.delim"          = "\t"
        "serialization.format" = "\t"
      }
    }

    # The 33 standard CloudFront log columns, in order.
    columns {
      name = "date"
      type = "date"
    }
    columns {
      name = "time"
      type = "string"
    }
    columns {
      name = "location"
      type = "string"
    }
    columns {
      name = "bytes"
      type = "bigint"
    }
    columns {
      name = "request_ip"
      type = "string"
    }
    columns {
      name = "method"
      type = "string"
    }
    columns {
      name = "host"
      type = "string"
    }
    columns {
      name = "uri"
      type = "string"
    }
    columns {
      name = "status"
      type = "int"
    }
    columns {
      name = "referrer"
      type = "string"
    }
    columns {
      name = "user_agent"
      type = "string"
    }
    columns {
      name = "query_string"
      type = "string"
    }
    columns {
      name = "cookie"
      type = "string"
    }
    columns {
      name = "result_type"
      type = "string"
    }
    columns {
      name = "request_id"
      type = "string"
    }
    columns {
      name = "host_header"
      type = "string"
    }
    columns {
      name = "request_protocol"
      type = "string"
    }
    columns {
      name = "request_bytes"
      type = "bigint"
    }
    columns {
      name = "time_taken"
      type = "float"
    }
    columns {
      name = "xforwarded_for"
      type = "string"
    }
    columns {
      name = "ssl_protocol"
      type = "string"
    }
    columns {
      name = "ssl_cipher"
      type = "string"
    }
    columns {
      name = "response_result_type"
      type = "string"
    }
    columns {
      name = "http_version"
      type = "string"
    }
    columns {
      name = "fle_status"
      type = "string"
    }
    columns {
      name = "fle_encrypted_fields"
      type = "int"
    }
    columns {
      name = "c_port"
      type = "int"
    }
    columns {
      name = "time_to_first_byte"
      type = "float"
    }
    columns {
      name = "x_edge_detailed_result_type"
      type = "string"
    }
    columns {
      name = "sc_content_type"
      type = "string"
    }
    columns {
      name = "sc_content_len"
      type = "bigint"
    }
    columns {
      name = "sc_range_start"
      type = "bigint"
    }
    columns {
      name = "sc_range_end"
      type = "bigint"
    }
  }
}


# Athena workgroup with a results location. Queries fail without one; results
# land in their own prefix, separate from the raw logs.
resource "aws_athena_workgroup" "main" {
  name = var.project

  configuration {
    result_configuration {
      output_location = "s3://${aws_s3_bucket.logs.bucket}/athena-results/"
    }
  }
}
