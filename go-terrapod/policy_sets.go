package terrapod

import (
	"context"
	"fmt"
	"net/url"
)

// PolicySet is an OPA policy set that scopes a collection of .rego
// policies to workspaces via label/name selectors.
type PolicySet struct {
	ID               string `json:"id"`
	Name             string `json:"name"`
	Description      string `json:"description,omitempty"`
	EnforcementLevel string `json:"enforcement-level"`
	Enabled          bool   `json:"enabled"`
	GlobalScope      bool   `json:"global-scope"`
	PolicyCount      int64  `json:"policy-count"`

	// Source discriminator: "inline" (default) or "vcs".
	Source string `json:"source"`

	// VCS fields (populated when Source == "vcs").
	// VCSConnectionID includes the "vcs-" prefix (e.g. "vcs-<uuid>"),
	// matching the format used by VCS connection endpoints.
	VCSConnectionID string `json:"vcs-connection-id,omitempty"`
	VCSRepoURL      string `json:"vcs-repo-url,omitempty"`
	VCSBranch       string `json:"vcs-branch,omitempty"`
	PolicyPath      string `json:"policy-path,omitempty"`
	VCSLastCommitSHA string `json:"vcs-last-commit-sha,omitempty"`
	VCSLastSyncedAt  string `json:"vcs-last-synced-at,omitempty"`
	VCSLastError     string `json:"vcs-last-error,omitempty"`

	CreatedAt string `json:"created-at,omitempty"`
	UpdatedAt string `json:"updated-at,omitempty"`
}

// CreatePolicySetRequest is the input shape for CreatePolicySet.
type CreatePolicySetRequest struct {
	Name             string
	Description      string
	EnforcementLevel string
	Enabled          bool
	GlobalScope      bool
	AllowLabels      map[string]string
	AllowNames       []string
	DenyLabels       map[string]string
	DenyNames        []string

	// VCS fields (set Source to "vcs" to create a VCS-backed set).
	Source          string
	VCSConnectionID string
	VCSRepoURL      string
	VCSBranch       string
	PolicyPath      string
}

// UpdatePolicySetRequest is the partial-update shape.
type UpdatePolicySetRequest struct {
	Name             *string
	Description      *string
	EnforcementLevel *string
	Enabled          *bool
	GlobalScope      *bool
	AllowLabels      map[string]string
	AllowNames       []string
	DenyLabels       map[string]string
	DenyNames        []string
	VCSRepoURL       *string
	VCSBranch        *string
	PolicyPath       *string
}

// CreatePolicySet creates a new policy set.
func (c *Client) CreatePolicySet(ctx context.Context, req CreatePolicySetRequest) (*PolicySet, error) {
	body, err := MarshalResource("policy-sets", policySetCreateAttrs(req), nil)
	if err != nil {
		return nil, fmt.Errorf("marshal create policy-set: %w", err)
	}
	data, err := c.Post(ctx, "/api/terrapod/v1/policy-sets", body)
	if err != nil {
		return nil, err
	}
	return parsePolicySet(data)
}

// GetPolicySet reads a policy set by id.
func (c *Client) GetPolicySet(ctx context.Context, id string) (*PolicySet, error) {
	data, err := c.Get(ctx, "/api/terrapod/v1/policy-sets/"+url.PathEscape(id))
	if err != nil {
		return nil, err
	}
	return parsePolicySet(data)
}

// ListPolicySets returns all policy sets.
func (c *Client) ListPolicySets(ctx context.Context) ([]PolicySet, error) {
	data, err := c.Get(ctx, "/api/terrapod/v1/policy-sets")
	if err != nil {
		return nil, err
	}
	resources, err := ParseResourceList(data)
	if err != nil {
		return nil, err
	}
	out := make([]PolicySet, 0, len(resources))
	for i := range resources {
		out = append(out, *policySetFromResource(&resources[i]))
	}
	return out, nil
}

// UpdatePolicySet patches a policy set.
func (c *Client) UpdatePolicySet(ctx context.Context, id string, req UpdatePolicySetRequest) (*PolicySet, error) {
	body, err := MarshalResourceWithID(id, "policy-sets", policySetUpdateAttrs(req))
	if err != nil {
		return nil, fmt.Errorf("marshal update policy-set: %w", err)
	}
	data, err := c.Patch(ctx, "/api/terrapod/v1/policy-sets/"+url.PathEscape(id), body)
	if err != nil {
		return nil, err
	}
	return parsePolicySet(data)
}

// DeletePolicySet removes a policy set and its policies.
func (c *Client) DeletePolicySet(ctx context.Context, id string) error {
	return c.Delete(ctx, "/api/terrapod/v1/policy-sets/"+url.PathEscape(id))
}

// SyncPolicySet triggers an immediate sync of a VCS-sourced policy set.
// Returns the policy set state at the time of enqueue (sync happens
// asynchronously). Returns an error if the policy set is not VCS-sourced.
func (c *Client) SyncPolicySet(ctx context.Context, id string) (*PolicySet, error) {
	path := fmt.Sprintf("/api/terrapod/v1/policy-sets/%s/actions/sync", url.PathEscape(id))
	data, err := c.Post(ctx, path, nil)
	if err != nil {
		return nil, err
	}
	return parsePolicySet(data)
}

// ── Internal helpers ─────────────────────────────────────────────────

func policySetCreateAttrs(req CreatePolicySetRequest) map[string]any {
	attrs := map[string]any{
		"name":              req.Name,
		"enforcement-level": req.EnforcementLevel,
		"enabled":           req.Enabled,
		"global-scope":      req.GlobalScope,
	}
	if req.Description != "" {
		attrs["description"] = req.Description
	}
	if len(req.AllowLabels) > 0 {
		attrs["allow-labels"] = req.AllowLabels
	}
	if len(req.AllowNames) > 0 {
		attrs["allow-names"] = req.AllowNames
	}
	if len(req.DenyLabels) > 0 {
		attrs["deny-labels"] = req.DenyLabels
	}
	if len(req.DenyNames) > 0 {
		attrs["deny-names"] = req.DenyNames
	}
	if req.Source != "" {
		attrs["source"] = req.Source
	}
	if req.VCSConnectionID != "" {
		attrs["vcs-connection-id"] = req.VCSConnectionID
	}
	if req.VCSRepoURL != "" {
		attrs["vcs-repo-url"] = req.VCSRepoURL
	}
	if req.VCSBranch != "" {
		attrs["vcs-branch"] = req.VCSBranch
	}
	if req.PolicyPath != "" {
		attrs["policy-path"] = req.PolicyPath
	}
	return attrs
}

func policySetUpdateAttrs(req UpdatePolicySetRequest) map[string]any {
	attrs := map[string]any{}
	if req.Name != nil {
		attrs["name"] = *req.Name
	}
	if req.Description != nil {
		attrs["description"] = *req.Description
	}
	if req.EnforcementLevel != nil {
		attrs["enforcement-level"] = *req.EnforcementLevel
	}
	if req.Enabled != nil {
		attrs["enabled"] = *req.Enabled
	}
	if req.GlobalScope != nil {
		attrs["global-scope"] = *req.GlobalScope
	}
	if req.AllowLabels != nil {
		attrs["allow-labels"] = req.AllowLabels
	}
	if req.AllowNames != nil {
		attrs["allow-names"] = req.AllowNames
	}
	if req.DenyLabels != nil {
		attrs["deny-labels"] = req.DenyLabels
	}
	if req.DenyNames != nil {
		attrs["deny-names"] = req.DenyNames
	}
	if req.VCSRepoURL != nil {
		attrs["vcs-repo-url"] = *req.VCSRepoURL
	}
	if req.VCSBranch != nil {
		attrs["vcs-branch"] = *req.VCSBranch
	}
	if req.PolicyPath != nil {
		attrs["policy-path"] = *req.PolicyPath
	}
	return attrs
}

func parsePolicySet(body []byte) (*PolicySet, error) {
	res, err := ParseResource(body)
	if err != nil {
		return nil, fmt.Errorf("parse policy-set response: %w", err)
	}
	return policySetFromResource(res), nil
}

func policySetFromResource(res *Resource) *PolicySet {
	return &PolicySet{
		ID:               res.ID,
		Name:             GetStringAttr(res, "name"),
		Description:      GetStringAttr(res, "description"),
		EnforcementLevel: GetStringAttr(res, "enforcement-level"),
		Enabled:          GetBoolAttr(res, "enabled"),
		GlobalScope:      GetBoolAttr(res, "global-scope"),
		PolicyCount:      GetIntAttr(res, "policy-count"),
		Source:           GetStringAttr(res, "source"),
		VCSConnectionID:  GetStringAttr(res, "vcs-connection-id"),
		VCSRepoURL:       GetStringAttr(res, "vcs-repo-url"),
		VCSBranch:        GetStringAttr(res, "vcs-branch"),
		PolicyPath:       GetStringAttr(res, "policy-path"),
		VCSLastCommitSHA: GetStringAttr(res, "vcs-last-commit-sha"),
		VCSLastSyncedAt:  GetStringAttr(res, "vcs-last-synced-at"),
		VCSLastError:     GetStringAttr(res, "vcs-last-error"),
		CreatedAt:        GetStringAttr(res, "created-at"),
		UpdatedAt:        GetStringAttr(res, "updated-at"),
	}
}
