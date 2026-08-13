@@
     def _validate_json_response(self, text: str) -> None:
@@
         self._validate_analysis_minimal_contract(data)
+    
+    # Backwards-compatible alias: some callers/tests expect the non-underscored name
+    validate_json_response = _validate_json_response
*** End Patch
