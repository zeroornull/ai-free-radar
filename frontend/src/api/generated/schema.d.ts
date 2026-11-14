export interface paths {
    "/api/app": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** App Info */
        get: operations["app_info_api_app_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/settings": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Read Settings */
        get: operations["read_settings_api_settings_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        /** Update Settings */
        patch: operations["update_settings_api_settings_patch"];
        trace?: never;
    };
    "/api/settings/reset": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Reset Settings */
        post: operations["reset_settings_api_settings_reset_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/settings/test": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Test Settings */
        post: operations["test_settings_api_settings_test_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/sources": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Sources */
        get: operations["list_sources_api_sources_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/sources/{source_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /** Save Source */
        put: operations["save_source_api_sources__source_id__put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/sources/{source_id}/entries": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Source Entries */
        get: operations["source_entries_api_sources__source_id__entries_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/sources/{source_id}/snapshots": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Source Snapshots */
        get: operations["source_snapshots_api_sources__source_id__snapshots_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/source-snapshots/{snapshot_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Source Snapshot */
        get: operations["source_snapshot_api_source_snapshots__snapshot_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/sources/{source_id}/replay": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Replay Source Rules */
        post: operations["replay_source_rules_api_sources__source_id__replay_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/leads": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Leads */
        get: operations["leads_api_leads_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/messages": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Messages */
        get: operations["messages_api_messages_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/resources": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Resources */
        get: operations["resources_api_resources_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/resources/{resource_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Resource Detail */
        get: operations["resource_detail_api_resources__resource_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/reviews": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Reviews */
        get: operations["reviews_api_reviews_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/resources/{resource_id}/review": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Review Resource */
        post: operations["review_resource_api_resources__resource_id__review_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/resources/{resource_id}/recheck": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Recheck Resource */
        post: operations["recheck_resource_api_resources__resource_id__recheck_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/tasks": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Tasks */
        get: operations["tasks_api_tasks_get"];
        put?: never;
        /** Start Task */
        post: operations["start_task_api_tasks_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/translations/backfill": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Backfill Translations */
        post: operations["backfill_translations_api_translations_backfill_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/messages/backfill": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Backfill Sources */
        post: operations["backfill_sources_api_messages_backfill_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/tasks/{task_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Task Detail */
        get: operations["task_detail_api_tasks__task_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/briefings": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Briefings */
        get: operations["briefings_api_briefings_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/briefings/{task_id}/download": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Download Briefing */
        get: operations["download_briefing_api_briefings__task_id__download_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/briefings/{task_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Briefing Detail */
        get: operations["briefing_detail_api_briefings__task_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
}
export type webhooks = Record<string, never>;
export interface components {
    schemas: {
        /** ApiError */
        ApiError: {
            /** Detail */
            detail: string;
        };
        /** AppRead */
        AppRead: {
            /** Version */
            version: string;
            default_scope: components["schemas"]["Scope"];
            /** Schedule Enabled */
            schedule_enabled: boolean;
            /** Schedule Time */
            schedule_time: string;
            active_run: components["schemas"]["RunRead"] | null;
            /** Categories */
            categories: {
                [key: string]: string;
            };
            /** Resource Statuses */
            resource_statuses: {
                [key: string]: string;
            };
            /** China Policies */
            china_policies: {
                [key: string]: string;
            };
            /** Review States */
            review_states: {
                [key: string]: string;
            };
            /** Open Leads */
            open_leads: number;
            /** Labels */
            labels: {
                [key: string]: string;
            };
        };
        /** BriefingRead */
        BriefingRead: {
            run: components["schemas"]["RunRead"];
            /** Html */
            html: string;
        };
        /**
         * Category
         * @enum {string}
         */
        Category: "text" | "image" | "video" | "speech" | "embedding" | "rerank";
        /** Change */
        Change: {
            /** Id */
            id?: string;
            /** Resource Id */
            resource_id: string;
            /** Task Id */
            task_id: string;
            /**
             * Kind
             * @enum {string}
             */
            kind: "new" | "changed" | "expired" | "restored";
            /** Before */
            before?: {
                [key: string]: unknown;
            };
            /** After */
            after?: {
                [key: string]: unknown;
            };
            /** Evidence */
            evidence?: components["schemas"]["Evidence"][];
            /**
             * Discovered At
             * Format: date-time
             */
            discovered_at?: string;
        };
        /**
         * CheckStatus
         * @enum {string}
         */
        CheckStatus: "success" | "failed" | "incomplete";
        /**
         * ChinaPolicy
         * @enum {string}
         */
        ChinaPolicy: "supported" | "unsupported" | "unknown";
        /**
         * CollectedMessage
         * @description A source report, kept separate from officially verified policy facts.
         */
        CollectedMessage: {
            policy: components["schemas"]["Policy"];
            /**
             * Offer Key
             * @default default
             */
            offer_key: string;
            /** Title */
            title: string;
            /** Summary */
            summary: string;
            /** Sources */
            sources: components["schemas"]["MessageSource"][];
            /** Published At */
            published_at?: string | null;
            /**
             * Ended
             * @default false
             */
            ended: boolean;
            /**
             * End Reason
             * @default
             */
            end_reason: string;
            /**
             * Title Zh
             * @default
             */
            title_zh: string;
            /**
             * Summary Zh
             * @default
             */
            summary_zh: string;
            /**
             * End Reason Zh
             * @default
             */
            end_reason_zh: string;
        };
        /** CreateTaskRequest */
        CreateTaskRequest: {
            /** Categories */
            categories: components["schemas"]["Category"][];
            /**
             * Region
             * @default global
             * @enum {string}
             */
            region: "global" | "china";
            /** Resource Ids */
            resource_ids?: string[];
        };
        /** Evidence */
        Evidence: {
            /** Id */
            id?: string;
            /** Field */
            field: string;
            /** Url */
            url: string;
            /** Quote */
            quote: string;
            /**
             * Source Type
             * @enum {string}
             */
            source_type: "official" | "community";
            /**
             * Checked At
             * Format: date-time
             */
            checked_at?: string;
            /** Official Domain */
            official_domain?: string | null;
        };
        /**
         * FreeType
         * @enum {string}
         */
        FreeType: "ongoing" | "limited" | "unknown";
        /** HTTPValidationError */
        HTTPValidationError: {
            /** Detail */
            detail?: components["schemas"]["ValidationError"][];
        };
        JsonValue: unknown;
        /** LeadRead */
        LeadRead: {
            resource: components["schemas"]["Resource"];
            review: components["schemas"]["ResourceReview"];
        };
        /** MessageSource */
        MessageSource: {
            /** Url */
            url: string;
            /**
             * Title
             * @default
             */
            title: string;
            /** Excerpt */
            excerpt: string;
            /**
             * Source Type
             * @default search
             * @enum {string}
             */
            source_type: "official" | "community" | "github" | "search" | "catalog";
            /**
             * Access
             * @default snippet
             * @enum {string}
             */
            access: "page" | "snippet" | "feed" | "catalog";
            /**
             * Source Id
             * @default
             */
            source_id: string;
            /**
             * External Id
             * @default
             */
            external_id: string;
            /** Published At */
            published_at?: string | null;
        };
        /** ModelDeployment */
        ModelDeployment: {
            /** Provider */
            provider: string;
            /** Model Id */
            model_id: string;
            /** Base Model */
            base_model: string;
            /** Source Url */
            source_url: string;
            /** Quote */
            quote: string;
        };
        /** NewsItem */
        NewsItem: {
            policy: components["schemas"]["Policy"];
            /**
             * Offer Key
             * @default default
             */
            offer_key: string;
            /** Title */
            title: string;
            /** Summary */
            summary: string;
            /** Sources */
            sources: components["schemas"]["MessageSource"][];
            /** Published At */
            published_at?: string | null;
            /**
             * Ended
             * @default false
             */
            ended: boolean;
            /**
             * End Reason
             * @default
             */
            end_reason: string;
            /**
             * Title Zh
             * @default
             */
            title_zh: string;
            /**
             * Summary Zh
             * @default
             */
            summary_zh: string;
            /**
             * End Reason Zh
             * @default
             */
            end_reason_zh: string;
            /** Id */
            id?: string;
            /** Resource Id */
            resource_id: string;
            /** Task Id */
            task_id: string;
            /**
             * Kind
             * @enum {string}
             */
            kind: "new" | "changed" | "expired" | "restored";
            /**
             * Discovered At
             * Format: date-time
             */
            discovered_at?: string;
            /**
             * First Seen At
             * Format: date-time
             */
            first_seen_at?: string;
        };
        /** Policy */
        Policy: {
            /** Provider */
            provider: string;
            /** Service */
            service: string;
            category: components["schemas"]["Category"];
            /**
             * Provider Domain
             * @default
             */
            provider_domain: string;
            /**
             * Service Key
             * @default
             */
            service_key: string;
            /**
             * Access Mode
             * @default unknown
             * @enum {string}
             */
            access_mode: "api" | "product" | "unknown";
            /** Resource Id */
            resource_id?: string | null;
            /** Aliases */
            aliases?: string[];
            /** Models */
            models?: string[];
            /**
             * Api Url
             * @default 未说明
             */
            api_url: string;
            /**
             * Docs Url
             * @default 未说明
             */
            docs_url: string;
            /** @default unknown */
            free_type: components["schemas"]["FreeType"];
            /**
             * Quota
             * @default 未说明
             */
            quota: string;
            /**
             * Quota Unit
             * @default 未说明
             */
            quota_unit: string;
            /**
             * Refresh Cycle
             * @default 未说明
             */
            refresh_cycle: string;
            /**
             * Rate Limit
             * @default 未说明
             */
            rate_limit: string;
            /**
             * Claim Conditions
             * @default 未说明
             */
            claim_conditions: string;
            /** Payment Required */
            payment_required?: boolean | null;
            /** Payment Method Required */
            payment_method_required?: boolean | null;
            /** Expires At */
            expires_at?: string | null;
            /**
             * Expiry Notes
             * @default 未说明
             */
            expiry_notes: string;
            /**
             * Region Restrictions
             * @default 未说明
             */
            region_restrictions: string;
            /** @default unknown */
            china_policy: components["schemas"]["ChinaPolicy"];
            /** Evidence */
            evidence?: components["schemas"]["Evidence"][];
            /** Quota Facts */
            quota_facts?: components["schemas"]["QuotaFact"][];
            /** Model Deployments */
            model_deployments?: components["schemas"]["ModelDeployment"][];
            /** Fact Warnings */
            fact_warnings?: string[];
            /** @default pending */
            status: components["schemas"]["ResourceStatus"];
            /** @default success */
            check_status: components["schemas"]["CheckStatus"];
            /**
             * Failure Reason
             * @default
             */
            failure_reason: string;
            /**
             * Quota Zh
             * @default
             */
            quota_zh: string;
            /**
             * Quota Unit Zh
             * @default
             */
            quota_unit_zh: string;
            /**
             * Refresh Cycle Zh
             * @default
             */
            refresh_cycle_zh: string;
            /**
             * Rate Limit Zh
             * @default
             */
            rate_limit_zh: string;
            /**
             * Claim Conditions Zh
             * @default
             */
            claim_conditions_zh: string;
            /**
             * Expiry Notes Zh
             * @default
             */
            expiry_notes_zh: string;
            /**
             * Region Restrictions Zh
             * @default
             */
            region_restrictions_zh: string;
            /**
             * Failure Reason Zh
             * @default
             */
            failure_reason_zh: string;
        };
        /** QuotaFact */
        QuotaFact: {
            /** Amount */
            amount?: number | null;
            /** Unit */
            unit: string;
            /**
             * Period
             * @default 未说明
             */
            period: string;
            /**
             * Scope
             * @default unspecified
             */
            scope: string;
            /**
             * Condition
             * @default
             */
            condition: string;
            /** Model Ids */
            model_ids?: string[];
            /** Source Url */
            source_url: string;
            /** Quote */
            quote: string;
            /**
             * Value Phrase
             * @default
             */
            value_phrase: string;
        };
        /** ResearchTrace */
        ResearchTrace: {
            /** Gap Id */
            gap_id: string;
            category: components["schemas"]["Category"];
            /** Query */
            query: string;
            /** Goal */
            goal: string;
            /** Trigger Url */
            trigger_url: string;
            /** Source Ids */
            source_ids?: string[];
            /** Result Urls */
            result_urls?: string[];
            /** New Evidence Urls */
            new_evidence_urls?: string[];
            /**
             * Stop Reason
             * @default pending
             * @enum {string}
             */
            stop_reason: "gap_resolved" | "no_new_evidence" | "budget_exhausted" | "provider_failed" | "duplicate_query" | "pending";
            /**
             * Search Calls
             * @default 0
             */
            search_calls: number;
            /**
             * Observed At
             * Format: date-time
             */
            observed_at?: string;
        };
        /** Resource */
        Resource: {
            /** Provider */
            provider: string;
            /** Service */
            service: string;
            category: components["schemas"]["Category"];
            /**
             * Provider Domain
             * @default
             */
            provider_domain: string;
            /**
             * Service Key
             * @default
             */
            service_key: string;
            /**
             * Access Mode
             * @default unknown
             * @enum {string}
             */
            access_mode: "api" | "product" | "unknown";
            /** Resource Id */
            resource_id?: string | null;
            /** Aliases */
            aliases?: string[];
            /** Models */
            models?: string[];
            /**
             * Api Url
             * @default 未说明
             */
            api_url: string;
            /**
             * Docs Url
             * @default 未说明
             */
            docs_url: string;
            /** @default unknown */
            free_type: components["schemas"]["FreeType"];
            /**
             * Quota
             * @default 未说明
             */
            quota: string;
            /**
             * Quota Unit
             * @default 未说明
             */
            quota_unit: string;
            /**
             * Refresh Cycle
             * @default 未说明
             */
            refresh_cycle: string;
            /**
             * Rate Limit
             * @default 未说明
             */
            rate_limit: string;
            /**
             * Claim Conditions
             * @default 未说明
             */
            claim_conditions: string;
            /** Payment Required */
            payment_required?: boolean | null;
            /** Payment Method Required */
            payment_method_required?: boolean | null;
            /** Expires At */
            expires_at?: string | null;
            /**
             * Expiry Notes
             * @default 未说明
             */
            expiry_notes: string;
            /**
             * Region Restrictions
             * @default 未说明
             */
            region_restrictions: string;
            /** @default unknown */
            china_policy: components["schemas"]["ChinaPolicy"];
            /** Evidence */
            evidence?: components["schemas"]["Evidence"][];
            /** Quota Facts */
            quota_facts?: components["schemas"]["QuotaFact"][];
            /** Model Deployments */
            model_deployments?: components["schemas"]["ModelDeployment"][];
            /** Fact Warnings */
            fact_warnings?: string[];
            /** @default pending */
            status: components["schemas"]["ResourceStatus"];
            /** @default success */
            check_status: components["schemas"]["CheckStatus"];
            /**
             * Failure Reason
             * @default
             */
            failure_reason: string;
            /**
             * Quota Zh
             * @default
             */
            quota_zh: string;
            /**
             * Quota Unit Zh
             * @default
             */
            quota_unit_zh: string;
            /**
             * Refresh Cycle Zh
             * @default
             */
            refresh_cycle_zh: string;
            /**
             * Rate Limit Zh
             * @default
             */
            rate_limit_zh: string;
            /**
             * Claim Conditions Zh
             * @default
             */
            claim_conditions_zh: string;
            /**
             * Expiry Notes Zh
             * @default
             */
            expiry_notes_zh: string;
            /**
             * Region Restrictions Zh
             * @default
             */
            region_restrictions_zh: string;
            /**
             * Failure Reason Zh
             * @default
             */
            failure_reason_zh: string;
            /** Id */
            id?: string;
            /**
             * First Seen At
             * Format: date-time
             */
            first_seen_at?: string;
            /**
             * Last Checked At
             * Format: date-time
             */
            last_checked_at?: string;
            /** Last Success At */
            last_success_at?: string | null;
            /**
             * Last Task Id
             * @default
             */
            last_task_id: string;
            /** Recommended At */
            recommended_at?: string | null;
            /** Messages */
            messages?: components["schemas"]["CollectedMessage"][];
        };
        /** ResourceDetailRead */
        ResourceDetailRead: {
            resource: components["schemas"]["Resource"];
            /** History */
            history: components["schemas"]["Change"][];
            review: components["schemas"]["ResourceReview"];
            /** Actions */
            actions: components["schemas"]["UserAction"][];
            /** Messages */
            messages?: components["schemas"]["NewsItem"][];
        };
        /**
         * ResourceReview
         * @description Human judgment kept apart from researched evidence.
         */
        ResourceReview: {
            /** Resource Id */
            resource_id: string;
            /** @default open */
            state: components["schemas"]["ReviewState"];
            /**
             * Favorite
             * @default false
             */
            favorite: boolean;
            /**
             * Note
             * @default
             */
            note: string;
            /**
             * Updated At
             * Format: date-time
             */
            updated_at?: string;
        };
        /**
         * ResourceStatus
         * @enum {string}
         */
        ResourceStatus: "active" | "pending" | "expired";
        /** ReviewRead */
        ReviewRead: {
            review: components["schemas"]["ResourceReview"];
            /** Actions */
            actions: components["schemas"]["UserAction"][];
        };
        /** ReviewRequest */
        ReviewRequest: {
            /**
             * Action
             * @enum {string}
             */
            action: "confirm" | "reject" | "ignore" | "reopen" | "favorite" | "unfavorite" | "note";
            /**
             * Note
             * @default
             */
            note: string;
        };
        /**
         * ReviewState
         * @enum {string}
         */
        ReviewState: "open" | "confirmed" | "rejected" | "ignored";
        /** RuleMatch */
        RuleMatch: {
            /** Rule Id */
            rule_id: string;
            /** Field */
            field: string;
            /** Action */
            action: string;
            /** Label */
            label: string;
        };
        /** RunRead */
        RunRead: {
            /** Id */
            id: string;
            /**
             * Trigger
             * @enum {string}
             */
            trigger: "manual" | "scheduled" | "catchup";
            scope: components["schemas"]["Scope"];
            /**
             * Status
             * @enum {string}
             */
            status: "running" | "success" | "partial" | "failed";
            /**
             * Started At
             * Format: date-time
             */
            started_at: string;
            /** Finished At */
            finished_at: string | null;
            /** Error */
            error: string;
            /** Notes */
            notes: string[];
            /** Schedule Day */
            schedule_day: string | null;
            stats: components["schemas"]["RunStats"] | null;
            /** Has Briefing */
            has_briefing: boolean;
            /** Research Traces */
            research_traces?: components["schemas"]["ResearchTrace"][];
        };
        /** RunStats */
        RunStats: {
            /**
             * Search Calls
             * @default 0
             */
            search_calls: number;
            /**
             * Fetch Calls
             * @default 0
             */
            fetch_calls: number;
            /**
             * Model Requests
             * @default 0
             */
            model_requests: number;
            /**
             * Input Tokens
             * @default 0
             */
            input_tokens: number;
            /**
             * Output Tokens
             * @default 0
             */
            output_tokens: number;
            /**
             * Cache Read Tokens
             * @default 0
             */
            cache_read_tokens: number;
            /**
             * Reasoning Tokens
             * @default 0
             */
            reasoning_tokens: number;
        };
        /** Scope */
        Scope: {
            /** Categories */
            categories?: components["schemas"]["Category"][];
            /**
             * Region
             * @default global
             * @enum {string}
             */
            region: "global" | "china";
            /** Resource Ids */
            resource_ids?: string[];
        };
        /** SettingFieldRead */
        SettingFieldRead: {
            value?: components["schemas"]["JsonValue"] | null;
            /**
             * Configured
             * @default false
             */
            configured: boolean;
            /**
             * Source
             * @enum {string}
             */
            source: "db" | "toml" | "default" | "env" | "missing" | "read_only";
        };
        /** SettingsPatchRequest */
        SettingsPatchRequest: {
            /** Version */
            version: number;
            /** Values */
            values?: {
                [key: string]: components["schemas"]["JsonValue"];
            };
            /** Secrets */
            secrets?: {
                [key: string]: string | null;
            };
        };
        /** SettingsRead */
        SettingsRead: {
            /** Version */
            version: number;
            /** Fields */
            fields: {
                [key: string]: components["schemas"]["SettingFieldRead"];
            };
        };
        /** SettingsResetRequest */
        SettingsResetRequest: {
            /** Version */
            version: number;
            /** Keys */
            keys: string[];
        };
        /** SettingsTestRead */
        SettingsTestRead: {
            /** Ok */
            ok: boolean;
            /** Detail */
            detail: string;
        };
        /** SettingsTestRequest */
        SettingsTestRequest: {
            /**
             * Target
             * @enum {string}
             */
            target: "model" | "search";
        };
        /** SourceDefinition */
        SourceDefinition: {
            /** Id */
            id?: string;
            /** Name */
            name: string;
            /** Url */
            url: string;
            /**
             * Kind
             * @default web
             * @enum {string}
             */
            kind: "web" | "feed" | "catalog";
            /** Categories */
            categories?: components["schemas"]["Category"][];
            /**
             * Source Type
             * @default community
             * @enum {string}
             */
            source_type: "official" | "community" | "github" | "catalog";
            /**
             * Official Domain
             * @default
             */
            official_domain: string;
            /**
             * Enabled
             * @default true
             */
            enabled: boolean;
            /**
             * Interval Seconds
             * @default 86400
             */
            interval_seconds: number;
            /** Include Selectors */
            include_selectors?: string[];
            /** Exclude Selectors */
            exclude_selectors?: string[];
            /** Ignore Patterns */
            ignore_patterns?: string[];
            /** Rules */
            rules?: components["schemas"]["SourceRule"][];
            /** Checked On */
            checked_on?: string | null;
            /**
             * Review Reason
             * @default
             */
            review_reason: string;
            /**
             * Reopen If
             * @default
             */
            reopen_if: string;
        };
        /** SourceEntry */
        SourceEntry: {
            /** Id */
            id?: string;
            /** Source Id */
            source_id: string;
            /** External Id */
            external_id: string;
            /** Url */
            url: string;
            /**
             * Title
             * @default
             */
            title: string;
            /**
             * Content
             * @default
             */
            content: string;
            /** Published At */
            published_at?: string | null;
            /**
             * First Seen At
             * Format: date-time
             */
            first_seen_at?: string;
            /**
             * Last Seen At
             * Format: date-time
             */
            last_seen_at?: string;
            /**
             * Content Hash
             * @default
             */
            content_hash: string;
            /**
             * Revision
             * @default 1
             */
            revision: number;
            /** Rule Matches */
            rule_matches?: components["schemas"]["RuleMatch"][];
            /**
             * Priority
             * @default 0
             */
            priority: number;
            /**
             * Needs Review
             * @default false
             */
            needs_review: boolean;
            /**
             * Raw Content
             * @default
             */
            raw_content: string;
            /**
             * Run Id
             * @default
             */
            run_id: string;
        };
        /** SourceRead */
        SourceRead: {
            definition: components["schemas"]["SourceDefinition"];
            state?: components["schemas"]["SourceState"] | null;
        };
        /** SourceRule */
        SourceRule: {
            /** Id */
            id?: string;
            /**
             * Field
             * @enum {string}
             */
            field: "title" | "content" | "url";
            /** Pattern */
            pattern: string;
            /**
             * Action
             * @default tag
             * @enum {string}
             */
            action: "tag" | "deprioritize" | "review";
            /** Label */
            label: string;
        };
        /** SourceSnapshot */
        SourceSnapshot: {
            /** Id */
            id?: string;
            /** Source Id */
            source_id: string;
            /** Url */
            url: string;
            /**
             * Fetched At
             * Format: date-time
             */
            fetched_at?: string;
            /** Raw Content */
            raw_content: string;
            /**
             * Content Type
             * @default
             */
            content_type: string;
            /** Text */
            text: string;
            /** Links */
            links?: string[];
            /** Raw Hash */
            raw_hash: string;
            /** Normalized Hash */
            normalized_hash: string;
            /** Config Hash */
            config_hash: string;
            /** Previous Id */
            previous_id?: string | null;
            /**
             * Text Diff
             * @default
             */
            text_diff: string;
            /** Added Links */
            added_links?: string[];
            /** Removed Links */
            removed_links?: string[];
            /**
             * Run Id
             * @default
             */
            run_id: string;
        };
        /** SourceState */
        SourceState: {
            /** Source Id */
            source_id: string;
            /** Last Checked At */
            last_checked_at?: string | null;
            /** Last Success At */
            last_success_at?: string | null;
            /**
             * Status
             * @default never
             * @enum {string}
             */
            status: "never" | "ok" | "error";
            /**
             * Error
             * @default
             */
            error: string;
            /**
             * Etag
             * @default
             */
            etag: string;
            /**
             * Last Modified
             * @default
             */
            last_modified: string;
            /** Last Snapshot Id */
            last_snapshot_id?: string | null;
            /**
             * Config Hash
             * @default
             */
            config_hash: string;
            /**
             * Entry Count
             * @default 0
             */
            entry_count: number;
            /** Window Oldest */
            window_oldest?: string | null;
            /**
             * Coverage Warning
             * @default
             */
            coverage_warning: string;
            /** Next Check At */
            next_check_at?: string | null;
        };
        /** TaskDetailRead */
        TaskDetailRead: {
            run: components["schemas"]["RunRead"];
            /** Changes */
            changes: components["schemas"]["Change"][];
            /** Messages */
            messages?: components["schemas"]["NewsItem"][];
        };
        /** UserAction */
        UserAction: {
            /** Id */
            id?: string;
            /** Resource Id */
            resource_id: string;
            /**
             * Action
             * @enum {string}
             */
            action: "confirm" | "reject" | "ignore" | "reopen" | "favorite" | "unfavorite" | "note";
            /** Before */
            before?: {
                [key: string]: unknown;
            };
            /** After */
            after?: {
                [key: string]: unknown;
            };
            /**
             * Created At
             * Format: date-time
             */
            created_at?: string;
        };
        /** ValidationError */
        ValidationError: {
            /** Location */
            loc: (string | number)[];
            /** Message */
            msg: string;
            /** Error Type */
            type: string;
            /** Input */
            input?: unknown;
            /** Context */
            ctx?: Record<string, never>;
        };
    };
    responses: never;
    parameters: never;
    requestBodies: never;
    headers: never;
    pathItems: never;
}
export type $defs = Record<string, never>;
export interface operations {
    app_info_api_app_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppRead"];
                };
            };
        };
    };
    read_settings_api_settings_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SettingsRead"];
                };
            };
        };
    };
    update_settings_api_settings_patch: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SettingsPatchRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SettingsRead"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ApiError"];
                };
            };
            /** @description Unprocessable Entity */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ApiError"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ApiError"];
                };
            };
        };
    };
    reset_settings_api_settings_reset_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SettingsResetRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SettingsRead"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ApiError"];
                };
            };
            /** @description Unprocessable Entity */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ApiError"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ApiError"];
                };
            };
        };
    };
    test_settings_api_settings_test_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SettingsTestRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SettingsTestRead"];
                };
            };
            /** @description Unprocessable Entity */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ApiError"];
                };
            };
            /** @description Bad Gateway */
            502: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ApiError"];
                };
            };
        };
    };
    list_sources_api_sources_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SourceRead"][];
                };
            };
        };
    };
    save_source_api_sources__source_id__put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                source_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SourceDefinition"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SourceRead"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ApiError"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ApiError"];
                };
            };
            /** @description Unprocessable Entity */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ApiError"];
                };
            };
        };
    };
    source_entries_api_sources__source_id__entries_get: {
        parameters: {
            query?: {
                limit?: number;
                offset?: number;
            };
            header?: never;
            path: {
                source_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SourceEntry"][];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ApiError"];
                };
            };
            /** @description Unprocessable Entity */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ApiError"];
                };
            };
        };
    };
    source_snapshots_api_sources__source_id__snapshots_get: {
        parameters: {
            query?: {
                limit?: number;
            };
            header?: never;
            path: {
                source_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SourceSnapshot"][];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ApiError"];
                };
            };
            /** @description Unprocessable Entity */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ApiError"];
                };
            };
        };
    };
    source_snapshot_api_source_snapshots__snapshot_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                snapshot_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SourceSnapshot"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ApiError"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    replay_source_rules_api_sources__source_id__replay_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                source_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SourceEntry"][];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ApiError"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ApiError"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    leads_api_leads_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["LeadRead"][];
                };
            };
        };
    };
    messages_api_messages_get: {
        parameters: {
            query?: {
                category?: string;
                include_ended?: boolean;
                resource_id?: string;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["NewsItem"][];
                };
            };
            /** @description Unprocessable Entity */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ApiError"];
                };
            };
        };
    };
    resources_api_resources_get: {
        parameters: {
            query?: {
                category?: string;
                china_policy?: string;
                status?: string;
                include_ended?: boolean;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Resource"][];
                };
            };
            /** @description Unprocessable Entity */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ApiError"];
                };
            };
        };
    };
    resource_detail_api_resources__resource_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                resource_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ResourceDetailRead"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ApiError"];
                };
            };
            /** @description Unprocessable Entity */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ApiError"];
                };
            };
        };
    };
    reviews_api_reviews_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ResourceReview"][];
                };
            };
        };
    };
    review_resource_api_resources__resource_id__review_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                resource_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ReviewRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ReviewRead"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ApiError"];
                };
            };
            /** @description Unprocessable Entity */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ApiError"];
                };
            };
        };
    };
    recheck_resource_api_resources__resource_id__recheck_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                resource_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            202: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RunRead"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ApiError"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ApiError"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    tasks_api_tasks_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RunRead"][];
                };
            };
        };
    };
    start_task_api_tasks_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CreateTaskRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            202: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RunRead"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ApiError"];
                };
            };
            /** @description Unprocessable Entity */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ApiError"];
                };
            };
        };
    };
    backfill_translations_api_translations_backfill_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            202: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RunRead"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ApiError"];
                };
            };
        };
    };
    backfill_sources_api_messages_backfill_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            202: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RunRead"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ApiError"];
                };
            };
        };
    };
    task_detail_api_tasks__task_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                task_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TaskDetailRead"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ApiError"];
                };
            };
            /** @description Unprocessable Entity */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ApiError"];
                };
            };
        };
    };
    briefings_api_briefings_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RunRead"][];
                };
            };
        };
    };
    download_briefing_api_briefings__task_id__download_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                task_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    "Content-Disposition"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "text/markdown": string;
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ApiError"];
                };
            };
            /** @description Unprocessable Entity */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ApiError"];
                };
            };
        };
    };
    briefing_detail_api_briefings__task_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                task_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["BriefingRead"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ApiError"];
                };
            };
            /** @description Unprocessable Entity */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ApiError"];
                };
            };
        };
    };
}
