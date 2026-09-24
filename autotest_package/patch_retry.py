#!/usr/bin/env python3
"""Ajoute 3 tentatives (avec retour d'erreur au LLM) à la génération des scripts de monitoring.

Usage (depuis ~/AUTOTEST/autotest_package) :
    python3 patch_retry.py [chemin/vers/web_test_generator.py]
Crée une sauvegarde .bak à côté du fichier.
"""
import re
import shutil
import sys

path = sys.argv[1] if len(sys.argv) > 1 else "autotest/core/web_test_generator.py"
source = open(path, encoding="utf-8").read()

NEW_BLOCK = '''        if monitoring:
            from ..monitoring.contract import validate_script

            prompts = PromptManager(os.path.join(
                os.path.dirname(os.path.dirname(__file__)), "config", "monitoring_prompts.yaml"))
            system_prompt = prompts.get_prompt("monitoring_script", "system")
            base_prompt = prompts.get_prompt("monitoring_script", "user").format(
                test_case=json.dumps(test_case), page_metadata=json.dumps(page_metadata),
                page_source=minimized_html)
            expected_url = (page_metadata or {}).get("url")
            user_prompt = base_prompt
            last_error = None
            for attempt in range(1, 4):
                response = self.llm.generate(system_prompt, user_prompt, model_type="selenium")
                code = self._extract_code_from_response(response)
                try:
                    calls = validate_script(code)
                    if expected_url and calls[0] != ("open", [expected_url]):
                        raise ValueError("The first call must be exactly ctx.open(%r)" % expected_url)
                    return code + "\\n"
                except Exception as exc:
                    last_error = exc
                    self.logger.warning(
                        "Monitoring script rejected (attempt %d/3): %s", attempt, exc)
                    user_prompt = (
                        base_prompt
                        + "\\n\\nYour previous script was rejected by the validator: " + str(exc)
                        + "\\nPrevious script:\\n" + str(code)
                        + "\\n\\nReturn ONLY a corrected script. Reminder: every target must be a dict"
                        " with at least one non-empty string key among text, aria_label, placeholder,"
                        " id, name, role (optionally plus tag); never use css, class, xpath or href"
                        " keys; never a tag-only target.")
            raise ValueError("Monitoring script invalid after 3 attempts: " + str(last_error))
'''

pattern = re.compile(r'        if monitoring:\n.*?            return code \+ "\\n"\n', re.DOTALL)
matches = pattern.findall(source)
if len(matches) != 1:
    sys.exit("Bloc `if monitoring:` introuvable ou ambigu (%d correspondances) : rien modifié." % len(matches))
if "Monitoring script invalid after 3 attempts" in source:
    sys.exit("Déjà patché : rien à faire.")

shutil.copyfile(path, path + ".bak")
patched = pattern.sub(lambda m: NEW_BLOCK, source, count=1)
open(path, "w", encoding="utf-8").write(patched)
print("OK : %s patché (sauvegarde : %s.bak)" % (path, path))
