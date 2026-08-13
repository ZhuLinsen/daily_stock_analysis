@@
             try:
                 record_llm_run_started(
                     model=getattr(self.config, "litellm_model", None),
                     call_type="analysis",
                 )
-                result = self.analyzer.analyze(
-                    enhanced_context,
-                    news_context=news_context,
-                    progress_callback=self._emit_progress,
-                    stream_progress_callback=_on_llm_stream,
-                    analysis_context_pack_summary=analysis_context_pack_summary,
-                )
-                llm_duration_ms = int((time.monotonic() - llm_started_at) * 1000)
-                record_llm_run(
-                    success=bool(result and getattr(result, "success", True)),
-                    model=getattr(result, "model_used", None) if result else None,
-                    call_type="analysis",
-                    duration_ms=llm_duration_ms,
-                    error_type=(
-                        None
-                        if result and getattr(result, "success", True)
-                        else "AnalysisResultError"
-                    ),
-                    error_message=(
-                        getattr(result, "error_message", None)
-                        if result and not getattr(result, "success", True)
-                        else ("LLM returned empty result" if result is None else None)
-                    ),
-                )
+                try:
+                    result = self.analyzer.analyze(
+                        enhanced_context,
+                        news_context=news_context,
+                        progress_callback=self._emit_progress,
+                        stream_progress_callback=_on_llm_stream,
+                        analysis_context_pack_summary=analysis_context_pack_summary,
+                    )
+                except (AttributeError, TypeError) as exc:
+                    # Compatibility / defensive guard:
+                    # If analyzer implementation is missing an expected attribute
+                    # (e.g. validate_json_response) or accepts different signature
+                    # surface, treat this as a per-stock failure but don't abort the
+                    # entire batch. This prevents a single missing method from
+                    # stopping all concurrent analysis tasks.
+                    logger.exception(
+                        "[%s] Analyzer compatibility error: %s. Marking this stock analysis as failed and continuing.",
+                        code,
+                        exc,
+                    )
+                    record_llm_run(
+                        success=False,
+                        model=getattr(self.config, "litellm_model", None),
+                        call_type="analysis",
+                        duration_ms=int((time.monotonic() - llm_started_at) * 1000),
+                        error_type=type(exc).__name__,
+                        error_message=str(exc),
+                    )
+                    result = None
+                else:
+                    llm_duration_ms = int((time.monotonic() - llm_started_at) * 1000)
+                    record_llm_run(
+                        success=bool(result and getattr(result, "success", True)),
+                        model=getattr(result, "model_used", None) if result else None,
+                        call_type="analysis",
+                        duration_ms=llm_duration_ms,
+                        error_type=(
+                            None
+                            if result and getattr(result, "success", True)
+                            else "AnalysisResultError"
+                        ),
+                        error_message=(
+                            getattr(result, "error_message", None)
+                            if result and not getattr(result, "success", True)
+                            else ("LLM returned empty result" if result is None else None)
+                        ),
+                    )
*** End Patch
