package terrapod

import (
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func newPolicySetFixture(t *testing.T) (*Client, *http.Request) {
	t.Helper()
	var lastReq *http.Request
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		lastReq = r.Clone(r.Context())
		if r.Body != nil {
			b, _ := io.ReadAll(r.Body)
			_ = r.Body.Close()
			lastReq.Body = io.NopCloser(strings.NewReader(string(b)))
		}
		w.Header().Set("Content-Type", "application/vnd.api+json")
		switch {
		case r.Method == http.MethodPost && r.URL.Path == "/api/terrapod/v1/policy-sets":
			w.WriteHeader(http.StatusCreated)
			_, _ = w.Write([]byte(`{"data":{"id":"polset-aaa","type":"policy-sets","attributes":{
			  "name":"sec-baseline","enforcement-level":"mandatory","enabled":true,
			  "global-scope":true,"source":"vcs","policy-count":3,
			  "vcs-connection-id":"vcs-aaa","vcs-repo-url":"https://github.com/org/policies",
			  "vcs-branch":"main","policy-path":"policies",
			  "vcs-last-commit-sha":"abc123","vcs-last-synced-at":"2026-05-28T00:00:00Z"
			}}}`))
		case r.Method == http.MethodGet && r.URL.Path == "/api/terrapod/v1/policy-sets":
			_, _ = w.Write([]byte(`{"data":[
			  {"id":"polset-aaa","type":"policy-sets","attributes":{"name":"sec-baseline","source":"inline","enabled":true,"enforcement-level":"advisory","policy-count":2}},
			  {"id":"polset-bbb","type":"policy-sets","attributes":{"name":"cost-controls","source":"vcs","enabled":true,"enforcement-level":"mandatory","policy-count":5}}
			]}`))
		case r.Method == http.MethodGet && strings.HasPrefix(r.URL.Path, "/api/terrapod/v1/policy-sets/"):
			_, _ = w.Write([]byte(`{"data":{"id":"polset-aaa","type":"policy-sets","attributes":{
			  "name":"sec-baseline","enforcement-level":"mandatory","enabled":true,
			  "global-scope":false,"source":"vcs","policy-count":3,
			  "vcs-connection-id":"vcs-aaa","vcs-repo-url":"https://github.com/org/policies",
			  "vcs-branch":"main","policy-path":"opa/","vcs-last-error":"branch not found"
			}}}`))
		case r.Method == http.MethodPatch:
			_, _ = w.Write([]byte(`{"data":{"id":"polset-aaa","type":"policy-sets","attributes":{
			  "name":"renamed","enforcement-level":"advisory","enabled":true,"source":"inline","policy-count":0
			}}}`))
		case r.Method == http.MethodPost && strings.HasSuffix(r.URL.Path, "/actions/sync"):
			w.WriteHeader(http.StatusAccepted)
			_, _ = w.Write([]byte(`{"data":{"id":"polset-aaa","type":"policy-sets","attributes":{
			  "name":"sec-baseline","source":"vcs","enabled":true,"enforcement-level":"mandatory","policy-count":3,
			  "vcs-last-commit-sha":"def456","vcs-last-synced-at":"2026-05-28T01:00:00Z"
			}}}`))
		case r.Method == http.MethodDelete:
			w.WriteHeader(http.StatusNoContent)
		default:
			http.Error(w, "unhandled", http.StatusNotFound)
		}
	}))
	t.Cleanup(srv.Close)
	c, err := NewClient(Options{BaseURL: srv.URL, Token: "t"})
	if err != nil {
		t.Fatal(err)
	}
	return c, lastReq
}

func TestCreatePolicySet_VCS(t *testing.T) {
	c, _ := newPolicySetFixture(t)
	ps, err := c.CreatePolicySet(t.Context(), CreatePolicySetRequest{
		Name:             "sec-baseline",
		EnforcementLevel: "mandatory",
		Enabled:          true,
		GlobalScope:      true,
		Source:           "vcs",
		VCSConnectionID:  "vcs-aaa",
		VCSRepoURL:       "https://github.com/org/policies",
		VCSBranch:        "main",
		PolicyPath:       "policies",
	})
	if err != nil {
		t.Fatal(err)
	}
	if ps.ID != "polset-aaa" {
		t.Errorf("ID = %q", ps.ID)
	}
	if ps.Source != "vcs" {
		t.Errorf("Source = %q", ps.Source)
	}
	if ps.VCSConnectionID != "vcs-aaa" {
		t.Errorf("VCSConnectionID = %q", ps.VCSConnectionID)
	}
	if ps.VCSRepoURL != "https://github.com/org/policies" {
		t.Errorf("VCSRepoURL = %q", ps.VCSRepoURL)
	}
	if ps.PolicyCount != 3 {
		t.Errorf("PolicyCount = %d", ps.PolicyCount)
	}
}

func TestListPolicySets(t *testing.T) {
	c, _ := newPolicySetFixture(t)
	list, err := c.ListPolicySets(t.Context())
	if err != nil {
		t.Fatal(err)
	}
	if len(list) != 2 {
		t.Fatalf("len = %d", len(list))
	}
	if list[1].Source != "vcs" {
		t.Errorf("list[1].Source = %q", list[1].Source)
	}
}

func TestGetPolicySet(t *testing.T) {
	c, _ := newPolicySetFixture(t)
	ps, err := c.GetPolicySet(t.Context(), "polset-aaa")
	if err != nil {
		t.Fatal(err)
	}
	if ps.VCSLastError != "branch not found" {
		t.Errorf("VCSLastError = %q", ps.VCSLastError)
	}
	if ps.PolicyPath != "opa/" {
		t.Errorf("PolicyPath = %q", ps.PolicyPath)
	}
}

func TestUpdatePolicySet(t *testing.T) {
	c, _ := newPolicySetFixture(t)
	name := "renamed"
	ps, err := c.UpdatePolicySet(t.Context(), "polset-aaa", UpdatePolicySetRequest{
		Name: &name,
	})
	if err != nil {
		t.Fatal(err)
	}
	if ps.Name != "renamed" {
		t.Errorf("Name = %q", ps.Name)
	}
}

func TestDeletePolicySet(t *testing.T) {
	c, _ := newPolicySetFixture(t)
	if err := c.DeletePolicySet(t.Context(), "polset-aaa"); err != nil {
		t.Fatal(err)
	}
}

func TestSyncPolicySet(t *testing.T) {
	c, _ := newPolicySetFixture(t)
	ps, err := c.SyncPolicySet(t.Context(), "polset-aaa")
	if err != nil {
		t.Fatal(err)
	}
	if ps.VCSLastCommitSHA != "def456" {
		t.Errorf("VCSLastCommitSHA = %q", ps.VCSLastCommitSHA)
	}
}
