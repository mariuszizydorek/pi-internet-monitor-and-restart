describe("live status", () => {
  it("shows the status page and the admin check", () => {
    cy.visit("/");
    cy.contains("Live status").should("be.visible");
    cy.contains("Admin").click();
    cy.contains("Test connectivity").should("be.visible");
  });
});
