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
            /** @default pending */
            status: components["schemas"]["ResourceStatus"];
            /** @default success */
            check_status: components["schemas"]["CheckStatus"];
            /**
             * Failure Reason
             * @default
             */
            failure_reason: string;
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
        };
        /** ResourceDetailRead */
        ResourceDetailRead: {
            resource: components["schemas"]["Resource"];
            /** History */
            history: components["schemas"]["Change"][];
            review: components["schemas"]["ResourceReview"];
            /** Actions */
            actions: components["schemas"]["UserAction"][];
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
        /** TaskDetailRead */
        TaskDetailRead: {
            run: components["schemas"]["RunRead"];
            /** Changes */
            changes: components["schemas"]["Change"][];
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
    resources_api_resources_get: {
        parameters: {
            query?: {
                category?: string;
                china_policy?: string;
                status?: string;
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
